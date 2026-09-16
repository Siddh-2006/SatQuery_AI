# System Design

SatQuery AI is an evidence-oriented remote-sensing analysis system. A user
selects satellite imagery, asks a natural-language question, and receives an
answer together with the evidence, confidence, specialist models used, and an
auditable execution trace. The system separates orchestration from specialist
Earth-observation models so that each query is routed to the model best suited
to its input context and task.

This document describes the system boundary and runtime behavior. Model
architecture decisions are recorded in [ADR 0001](adr/0001-orchestrator-choice.md)
through [ADR 0005](adr/0005-segmentation-model-choice.md); implementation
details belong in [02-technical-approach.md](02-technical-approach.md).

## 1. End-to-End Architecture

The frontend is a map-and-chat workspace. It sends a typed input context and a
natural-language query to the API; it never invokes a model directly. The
backend retrieves the matching raster inputs, the Gemma 4 E2B agentic
orchestrator validates and routes the request, and the selected specialist
returns an observation for integration into one structured response.

The diagram below is the system's complete flow. Specialist branches are
capability-gated by the model/tool registry: a branch is dispatchable only when
its implementation is registered and marked ready. The branch architecture and
model choices are defined in [ADR 0001](adr/0001-orchestrator-choice.md)
through [ADR 0005](adr/0005-segmentation-model-choice.md).

```mermaid
flowchart TD
	U[User / analyst] --> I[Input layer\nMap selection, area, point, upload\nNatural-language query]
	I --> C[Typed context set\nSingle image, bi-temporal pair,\nor optical + SAR pair]
	C --> API[Frontend API boundary\nFastAPI query and data endpoints]

	API --> D[Backend and data retrieval\nPatch index, metadata, GeoTIFF/TIFF\nband resolution and cached inputs]
	D --> Q[Query + resolved input context]
	Q --> O[Gemma 4 E2B\nAgentic orchestrator]

	O --> V{Intent and compatibility\nvalidation}
	V -->|Unsupported task, modality,\nor invalid context| R[Structured rejection\nAPI error]
	V -->|Valid context| S[Specialist selection\nCapability-aware tool registry]

	S --> B1[Single-image branch\nTinyRS-R1]
	B1 --> T1[VQA\nGrounding\nCaptioning]

	S --> B2[Bi-temporal branch\nDeltaVLM]
	B2 --> T2[Change VQA\nChange map / localization]

	S --> B3[Optical + SAR branch\nTerraFM-based fusion]
	B3 --> T3[Fused multisensor\nreasoning]

	S --> B4[Segmentation branch\nSAM / TerraFM + UperNet]
	B4 --> T4[Segmentation mask\nPrompt or thematic output]

	T1 --> E[Specialist execution]
	T2 --> E
	T3 --> E
	T4 --> E
	E --> O1[Observation returned to orchestrator]
	O1 --> W{Observation validation}
	W -->|Malformed output and retry available| Retry[Corrective instruction\nRetry specialist step]
	Retry --> O
	W -->|Valid, or retry exhausted| G[Integration and response composition]
	O -->|Final answer or step limit| G

	G --> F[Final output layer]
	F --> A[Natural-language answer]
	F --> Conf[Confidence score]
	F --> Trace[Execution trace\nTask, models, parameters]
	F --> Evidence[Visual evidence\nBoxes, masks, change regions]
	F --> Report[Persisted report]
	A --> API
	Conf --> API
	Trace --> API
	Evidence --> API
	Report --> API
	API --> U
```

The architecture has three useful boundaries:

| Boundary | Responsibility |
| --- | --- |
| Frontend/API | Context selection, upload and preview interactions, query transport, session display, map overlays, and report download. |
| Orchestrator | Understand the request, verify that the context is usable, select and sequence tools, validate observations, and compose the response. |
| Specialist layer | Perform domain-specific visual reasoning and return task-shaped observations such as text, coordinates, masks, or change evidence. |

## 2. Inputs And Context

Every query carries a session identifier, natural-language question, and a
typed context set. The context identifies the imagery and its relationship:

| Context | Analysis represented |
| --- | --- |
| `single` | One optical or multispectral scene, optionally with supported SAR bands. |
| `cross_modal_pair` | Co-registered optical and SAR observations of the same area. |
| `bitemporal_pair` | Observations of the same area at two different times. |

Patch footprints and metadata are selected in the map interface. The data
layer resolves those references to the required raster bands, preserves the
spatial metadata needed by downstream models, and provides previews without
making the browser interpret GeoTIFF pixels. Uploads and area selections use
the same context-set boundary, so the rest of the query pipeline receives a
consistent request shape.

```mermaid
flowchart TD
		Select[Map footprint, area, point, or uploaded imagery] --> Context[Typed context set]
		Context --> Check{Compatibility and metadata checks}
		Check -->|invalid task or context| Reject[Structured API error]
		Check -->|valid| Resolve[Resolve patch references and imagery]
		Resolve --> Ready[Resolved model inputs\nmodality, bands, location, time]
```

Compatibility is checked before model inference. The check covers the context
type, available modalities, spatial relationship between paired images, and
whether the requested task has a registered specialist. This makes unsupported
requests explicit instead of silently substituting a different analysis.

## 3. Orchestrator And Execution Graph

The orchestrator is implemented as a LangGraph `StateGraph`. Its state carries
the query, resolved imagery, conversation messages, tool calls, observations,
retry state, and final answer. The graph is deterministic at the workflow
level even though the main model chooses the next specialist action.

```mermaid
flowchart TD
		Start([Query request]) --> Compat[Check compatibility]
		Compat -->|reject| Error[Return structured error]
		Compat -->|accept| Resolve[Resolve imagery and patches]
		Resolve -->|failure| Error
		Resolve --> Seed[Seed task and context prompt]
		Seed --> Think[Gemma 4 agent step]
		Think -->|specialist action| Execute[Execute registered tool]
		Execute --> Observe[Collect observation]
		Observe --> Validate[Validate output shape]
		Validate -->|malformed and retry available| Corrective[Add corrective instruction]
		Corrective --> Think
		Validate -->|valid or retry exhausted| Think
		Think -->|final answer or step limit| Compose[Compose response]
		Compose --> Done([Answer, evidence, confidence, trace, report])
```

### Runtime stages

1. **Compatibility check:** verifies that the context and requested operation
	 can be handled by the registered specialist layer.
2. **Input resolution:** maps patch references to the relevant optical,
	 multispectral, and/or SAR raster inputs and keeps file-system details out of
	 the model conversation.
3. **Prompt seeding:** gives the main model the user question, spatial and
	 temporal context, available tools, and each tool's required output shape.
4. **Agent step:** the Gemma 4 orchestrator decides whether to call a tool,
	 which tool to call, and how to express the specialist instruction.
5. **Tool execution:** dispatches only to tools marked ready by the registry.
	 Specialist results return to the graph as observations.
6. **Observation validation:** checks that the result matches the requested
	 response shape, including lettered answers and coordinate-bearing grounding
	 results. A bounded corrective retry handles malformed observations.
7. **Answer composition:** converts the final model response and structured
	 observations into the frontend contract, persists the turn, and creates a
	 downloadable report.

## 4. Model And Tool Registry

The registry is the control point between orchestration and inference. A
specialist contributes a capability description, prompt contract, and tool
implementation. The orchestrator exposes only registered, ready capabilities;
future or unavailable tools cannot be selected merely because the main model
mentions them.

```mermaid
flowchart LR
		Registry[Capability registry] --> Contract[Task and input contract]
		Registry --> Dispatch[Tool dispatch]
		Contract --> Main[Gemma 4 orchestrator]
		Dispatch --> Models[Specialist models]
		Models --> Observation[Typed observation]
		Observation --> Main
```

The specialist responsibilities follow the architectural decisions:

| Specialist responsibility | Enabled analysis | Decision record |
| --- | --- | --- |
| Single-image optical understanding | Scene captioning, VQA, and spatial grounding. | [ADR 0002](adr/0002-single-image-model-choice.md) |
| Optical-SAR fusion | Joint reasoning over complementary, co-registered sensors. | [ADR 0003](adr/0003-fusion-encoder-choice.md) |
| Bi-temporal change understanding | Change verification, direction, magnitude, comparison, and localization. | [ADR 0004](adr/0004-change-detection-architecture.md) |
| Segmentation | Prompt-based masks and dense thematic land-cover segmentation. | [ADR 0005](adr/0005-segmentation-model-choice.md) |

The orchestrator choice, state transitions, and registry policy are specified
in [ADR 0001](adr/0001-orchestrator-choice.md). This document intentionally
does not repeat the internal encoder, adapter, loss, or training details from
those ADRs.

## 5. Evidence, Confidence, And Trace

SatQuery AI treats an answer as a structured analysis result rather than plain
text. The response can contain:

- **Answer:** the natural-language explanation generated from the specialist
	observation(s).
- **Evidence:** spatial objects such as normalized bounding boxes or masks,
	associated with the relevant patch and label for map visualization.
- **Confidence:** the confidence value exposed by the response contract,
	allowing the interface to communicate how strongly the result is supported.
- **Execution trace:** the classified task, models used, tool-call count, and
	key parameters needed to audit how the answer was produced.
- **Report:** a persisted representation of the query, answer, evidence,
	confidence, and trace for later review or download.

```mermaid
sequenceDiagram
		participant U as User
		participant UI as Frontend
		participant O as Orchestrator
		participant M as Specialist model
		participant R as Report store

		U->>UI: Ask question with selected context
		UI->>O: Query + typed context set
		O->>M: Validated task instruction and resolved imagery
		M-->>O: Observation and task evidence
		O->>O: Validate, classify, and compose
		O->>R: Persist report and execution trace
		O-->>UI: Answer + evidence + confidence + trace + report URL
		UI-->>U: Text, map overlay, trace, and downloadable report
```

The trace makes the system inspectable: an analyst can see what task was
classified, which specialist participated, and what evidence was returned.
Validation and explicit structured errors prevent malformed or unsupported
results from being presented as ordinary successful answers.

## 6. Related Documentation

- [02-technical-approach.md](02-technical-approach.md): implementation and
	deployment approach.
- [03-models-and-metrics.md](03-models-and-metrics.md): model evaluation and
	measurement plan.
- [04-user-flow.md](04-user-flow.md): analyst interaction flow.
- [09-deployment.md](09-deployment.md): deployment concerns.
- [ADR index](adr/0001-orchestrator-choice.md): authoritative architectural
	decisions.
