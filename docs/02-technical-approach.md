# Technical Approach

SatQuery AI combines a typed imagery context, a FastAPI service boundary, a
LangGraph orchestration loop, and specialist model services. This document
focuses on how a request is processed internally. The system boundary is
described in [01-system-design.md](01-system-design.md); architectural and
model decisions are recorded in [ADR 0001](adr/0001-orchestrator-choice.md)
through [ADR 0005](adr/0005-segmentation-model-choice.md).

## 1. Request Processing Path

The main request enters through `POST /api/query`. The route persists the user
message and context set, invokes the compiled graph, converts its final state
to the response contract, persists the assistant message, and publishes the
completion event. Model-specific logic stays behind the graph and tool
boundaries.

```mermaid
sequenceDiagram
		participant UI as Frontend
		participant API as POST /api/query
		participant DB as Session store
		participant G as LangGraph StateGraph
		participant Data as Patch/data layer
		participant Tool as Ready specialist tool
		participant Report as Report store

		UI->>API: sessionId + query + contextSet
		API->>DB: Upsert context and user message
		API->>G: Run query with context
		G->>Data: Validate and resolve imagery
		Data-->>G: Resolved patch inputs
		G->>Tool: Execute selected specialist instruction
		Tool-->>G: Raw observation
		G->>G: Validate, retry if required, compose answer
		G-->>API: Final graph state
		API->>Report: Write answer, evidence, confidence, trace
		API->>DB: Persist assistant message
		API-->>UI: Structured query response
```

## 2. Input Contract And Validation

The frontend submits a `contextSet` that identifies the imagery relationship
and its items. The current context types are `single`, `bitemporal_pair`, and
`cross_modal_pair`. Items may refer to indexed patches, area selections, or
uploads. The API stores the submitted context before inference so that the
session remains inspectable even when a request is rejected.

The authoritative pre-flight check is
`app/compatibility.py::check_query_compatible`. It runs before the main model
is invoked and returns the API's structured error shape when:

- no ready registry tool supports the requested context type;
- a query refers to an uploaded image that is storable and previewable but not
	connected to the current specialist input path; or
- a patch requests SAR alone even though the ready single-image specialist
	requires optical input and accepts SAR only as an additional modality.

This is a capability check, not a language-model guess. It prevents an
unsupported task from being converted into an apparently valid answer.

```mermaid
flowchart TD
		Request[Query request] --> Shape[Read session, query, context set]
		Shape --> Compat{Context and capability check}
		Compat -->|Unsupported or incompatible| Error[422 structured API error]
		Compat -->|Accepted| Resolve[Resolve indexed patch inputs]
		Resolve -->|Unknown patch or missing optical capture| Error
		Resolve -->|Resolved| Prompt[Build model context]
```

## 3. Patch Resolution And Raster Preparation

The patch layer separates user-facing patch identifiers from archive layout.
The footprint index loads the repository's patch fixture records and maps a
short patch ID to region, tile, row, column, location, available modalities,
and capture dates. The resolver then scans the BigEarthNet archive indexes for
the matching optical capture and, when requested, the SAR capture.

Only the selected bands are extracted from the archive into the orchestrator
cache. Extraction is skipped when the target file is already present. The
resulting `ResolvedPatch` contains the optical and optional SAR directories,
the full archive patch IDs, and the paths passed to the specialist service.

```mermaid
flowchart LR
		PatchID[Short patch ID] --> Footprint[Patch footprint index]
		Footprint --> Key[Region, tile, row, column]
		Key --> Archives[(BigEarthNet S1/S2 archives)]
		Archives --> Match[Latest matching capture]
		Match --> Extract[Extract required GeoTIFF bands]
		Extract --> Cache[(Patch cache)]
		Cache --> Resolved[ResolvedPatch\nS2 path + optional S1 path]
```

For the ready single-image path, optical bands are always required. The
optional SAR path adds `VV` and `VH` bands when the context requests full
bands; it does not turn an SAR-only context into a supported query. Preview
generation uses the same resolved source and can render true-colour,
false-colour, or SAR composites without sending those preview pixels through
the browser.

## 4. Prompt Construction And Task Interpretation

The main model receives operational context, not raw filesystem paths. The
prompt builder includes the resolved patch IDs and available modalities, the
mission rules, and the system prompt of every ready tool. This constrains the
agent to patch IDs supplied for the current turn and to the output shapes that
the selected specialist understands.

For the local Gemma 4 path, the ready tool schemas are rendered into a
structured JSON action format. The graph parses one action into a typed tool
call or a final answer. The graph owns this translation so the tool
implementation can receive resolved files as a normal function argument while
the model sees only its public `patch_id` and `instruction` contract.

The ready single-image specialist defines four instruction shapes:

| Shape | Internal result used by the response builder |
| --- | --- |
| Scene caption | Natural-language scene description. |
| Binary question | Direct yes/no visual answer. |
| Lettered MCQ | VQA answer with a lettered choice. |
| Point/reference grounding | Coordinate-bearing bounding-box answer. |

The detailed prompt contract is kept with the specialist under
`orchestrator/system_prompts/` and its model decision is in [ADR 0002](adr/0002-single-image-model-choice.md).

## 5. LangGraph Orchestration

`app/graph.py` compiles one `StateGraph` and supplies per-request state at
invocation time. The state contains the query, context, resolved patches,
messages, tool-call records, step count, malformed-output retry count, error,
and final answer.

```mermaid
flowchart TD
		A[check_compatibility] -->|error| X[reject]
		A -->|valid| B[resolve_patches]
		B -->|error| X
		B -->|valid| C[seed_prompt]
		C --> D[agent_step]
		D -->|tool call| E[execute_tools]
		E --> F[validate_observation]
		F -->|malformed and retry available| G[Corrective message]
		G --> D
		F -->|valid or retry exhausted| D
		D -->|final answer or step limit| H[compose_answer]
		H --> END([End])
		X --> END
```

The graph's control decisions are deliberately separate from model output:

1. `check_compatibility` rejects unsupported context before inference.
2. `resolve_patches` supplies actual raster locations to the tool call.
3. `seed_prompt` creates the system and user messages for the turn.
4. `agent_step` asks Gemma 4 to select a ready tool or provide a final answer.
5. `execute_tools` dispatches registered implementations and records raw
	 observations.
6. `validate_observation` checks output shape and adds one corrective nudge for
	 malformed MCQ or grounding results when a retry is available.
7. `compose_answer` selects the last non-tool-call answer and ends the graph.

The graph also has a bounded step count. This prevents a model that continues
to request actions from holding a request open indefinitely.

## 6. Capability Registry And Specialist Execution

The registry reads each specialist's `capabilities.json`. A tool is exposed to
the agent and dispatchable by the graph only when its status is `ready` and a
real implementation is present in `tools/registry.py`. The current ready
implementation is `query_eocaptioner`; change detection, cross-modal fusion,
and segmentation are represented by capability contracts but are not exposed
as runnable tools in the current build.

```mermaid
flowchart LR
		Spec[capabilities.json + system prompt] --> Gate{status = ready\nand implementation registered?}
		Gate -->|no| Hidden[Not exposed to agent]
		Gate -->|yes| Schema[Tool schema in prompt]
		Schema --> Call[Graph dispatch]
		Call --> Impl[Specialist implementation]
		Impl --> Obs[Raw observation]
```

### Ready single-image pipeline

`run_eocaptioner` verifies that the requested patch was resolved and contains
optical input, builds a request with the optical directory, optional SAR
directory, archive patch ID, and templated instruction, then calls the
specialist service. Expected service failures are returned as an `ERROR:`
observation so the graph can handle them as part of the conversation rather
than losing the whole request to an unstructured exception.

Inside the offline specialist server, the implementation loads the configured
optical bands and optional SAR bands from GeoTIFF files, normalizes and resizes
them, extracts TerraFM visual tokens, projects them through the Q-Former
projector, concatenates the resulting visual embeddings with tokenized text,
and streams the language-model answer. The model bundle is local to the
specialist service; the orchestrator communicates through its HTTP generation
endpoint.

```mermaid
flowchart TD
		Input[Resolved S2 bands\noptional S1 VV/VH] --> Load[Read GeoTIFF bands]
		Load --> Norm[Normalize and resize tensors]
		Norm --> Terra[TerraFM visual encoder]
		Terra --> Project[Q-Former projection]
		Project --> Embed[Visual embeddings + instruction embeddings]
		Embed --> Generate[Specialist language generation]
		Generate --> Raw[Streamed raw text observation]
```

### Other specialist pipelines

The repository keeps the chosen pipelines and contracts for additional tasks
without presenting them as available dispatch targets prematurely:

| Task path | Architectural implementation | Current integration boundary |
| --- | --- | --- |
| Bi-temporal change understanding | DeltaVLM / BiTemporal v2 with TerraFM features, DeltaBlock, TCSSM, projector, and TinyRS-R1 decoder. | Capability specification exists; registry status is not ready. See [ADR 0004](adr/0004-change-detection-architecture.md). |
| Optical-SAR fusion | Dual-branch TerraFM representation with gated cross-attention and language alignment. | Capability specification exists; registry status is not ready. See [ADR 0003](adr/0003-fusion-encoder-choice.md). |
| Prompt or thematic segmentation | SAM prompt masking and TerraFM-UperNet LULC segmentation. | The direct segmentation endpoint reports that the model is not integrated in normal operation; capability specification is not ready. See [ADR 0005](adr/0005-segmentation-model-choice.md). |

The internal architectures, training choices, and rationale remain in those
ADRs rather than being duplicated here.

## 7. Observation Validation And Output Integration

The validation node examines the relationship between the instruction shape
and raw observation. An MCQ instruction is expected to produce a lettered
answer; a point/reference grounding instruction is expected to produce
coordinate-shaped output. A malformed result receives one corrective prompt;
after the retry limit, the graph proceeds without claiming that the raw shape
was valid.

`response_builder.py` then performs the output integration:

- classifies the task from the final specialist instruction;
- extracts coordinate-shaped grounding results into structured bounding-box
	evidence linked to the patch ID;
- records ready model metadata and tool-call count in `executionTrace`;
- returns the answer, evidence, confidence, trace, and report URL in the API
	response shape; and
- writes the same information to a JSON report for later download.

The current response contract does not create reliable text-span grounding,
and the single-image specialist does not provide a calibrated confidence
signal. The response therefore exposes the configured confidence field while
keeping evidence limited to what the result parser can identify.

```mermaid
sequenceDiagram
		participant S as Specialist
		participant G as Graph state
		participant V as Observation validator
		participant B as Response builder
		participant R as Report store

		S-->>G: Raw text observation
		G->>V: Instruction + observation
		alt Shape is malformed and retry available
				V-->>G: Corrective instruction
				G->>S: Retry
		else Valid or retry exhausted
				V-->>G: Continue
				G->>B: Final answer + tool-call records
				B->>B: Parse bbox evidence and classify task
				B->>R: Persist report
				B-->>G: Structured response fields
		end
```

## 8. Adjacent API Paths

Not every imagery operation enters the agent graph:

- `POST /api/uploads` stores an uploaded file, detects available metadata, and
	serves a preview. Querying that upload is rejected by the current
	compatibility layer.
- Patch preview endpoints resolve imagery and render server-side composites.
- `POST /api/segment` is a direct UI path. In normal operation it returns an
	explicit not-integrated error because the segmentation model is not ready;
	its demo behavior is kept separate from the real query pipeline.
- Session and report endpoints expose persisted context, messages, and
	response artifacts.

This separation keeps interactive map operations and model-orchestrated
questions from being confused with one another.
