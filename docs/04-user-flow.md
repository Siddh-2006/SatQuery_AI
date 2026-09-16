# User Flow

SatQuery AI presents satellite analysis as a map-and-chat workflow. The user
first builds an explicit imagery context, then asks a natural-language
question against that context. The interface shows progress while the request
is processed and returns text together with any available spatial evidence,
confidence, execution trace, and report link.

The frontend contract and interaction design are defined in [ui/DESIGN.md](../ui/DESIGN.md).
The internal processing path is documented in [02-technical-approach.md](02-technical-approach.md).

## 1. End-to-End Journey

```mermaid
flowchart TD
	Start([Open SatQuery AI]) --> Session[Create or load session]
	Session --> Browse[Browse map footprints and metadata]
	Browse --> Choice{How will imagery enter context?}
	Choice -->|Select patch| Patch[Choose indexed patch]
	Choice -->|Draw area| Area[Draw freehand area]
	Choice -->|Upload imagery| Upload[Upload GeoTIFF, TIFF, PNG, or JPEG]
	Choice -->|Temporal browser| Pair[Choose two captures at one location]
	Patch --> Inspect[Inspect preview, date, modality, and location]
	Area --> Pending[Review pending selection]
	Upload --> UploadCheck[Preview detected metadata]
	Pair --> PairCheck[Confirm same location and distinct dates]
	Inspect --> Confirm[Add item to context]
	Pending --> Confirm
	UploadCheck --> Confirm
	PairCheck --> Confirm
	Confirm --> Context[Active typed context set]
	Context --> Validate{Client/API compatibility validation}
	Validate -->|Invalid or unsupported| Explain[Show actionable error]
	Validate -->|Accepted| Ask[Enter natural-language query]
	Ask --> Submit[Submit query with session and context]
	Submit --> Progress[Watch live activity and execution trace]
	Progress --> Result[Read answer and inspect evidence]
	Result --> Report[Open trace or download report]
```

The context is never implicit: a query is submitted with the active context
set, and the user can remove or replace its items before sending.

## 2. Build The Imagery Context

### Select an indexed patch

The map displays patch footprints returned by the backend. Selecting a
footprint opens metadata such as patch ID, label, location, available
modalities, and capture dates. The user can inspect a server-rendered
true-colour, false-colour, or SAR preview before adding the patch to context.

The map basemap is for geographic orientation. The selected footprint is the
actual dataset reference that the backend resolves to raster files.

### Draw an area

Free draw creates a user-authored polygon on the map. The frontend checks which
known footprints it overlaps and shows the resulting patch count before the
user confirms it. Area selections are limited to a `single` context set in the
current interaction contract because pairing an arbitrary shape across dates or
modalities is not yet defined.

### Upload imagery

The upload dialog accepts the formats supported by the API upload route:
GeoTIFF/TIFF and common PNG/JPEG image files. The user sees upload progress,
then a pending card with the returned preview, detected modality, location,
timestamp, and filename. Missing metadata can be completed in the context
workflow before confirmation.

The current backend stores uploads and serves previews, but the authoritative
query compatibility check does not yet allow uploaded imagery to be sent to the
ready specialist. The user therefore receives an explicit incompatibility
message rather than an answer generated from unsupported input.

### Prepare a pair

The context manager supports two-image sets:

| Context | User action | Current query outcome |
| --- | --- | --- |
| `single` | Add one indexed patch, area selection, or upload. | Indexed patch queries can proceed through the ready single-image specialist; uploads are stored/previewable but rejected for querying. |
| `bitemporal_pair` | Select two captures at the same location with different timestamps. | The UI and API contracts represent the flow, but the current registry has no ready change-detection tool, so the query is rejected as unsupported. |
| `cross_modal_pair` | Provide co-located optical and SAR imagery. | The context shape is defined, but the current registry has no ready fusion tool, so the query is rejected as unsupported. |

The UI prevents unrelated patches from being silently combined into a pair and
keeps area selections out of pair contexts. These checks improve the quality
of the request before the user reaches the submit step.

## 3. Query Submission

Once a context is valid, the user enters a question such as:

- “Describe the land cover in this patch.”
- “Is there a water body in this image?”
- “Locate the built-up area near this point.”
- “What changed between these two dates?”
- “Use the optical and SAR images together to identify built-up regions.”

The prompt is sent with the active session and context set. There is no
no-image query mode in the current contract.

```mermaid
sequenceDiagram
	participant User
	participant UI as Map and chat UI
	participant API as Query API
	participant Graph as Orchestrator graph
	participant Specialist

	User->>UI: Enter question and press send
	UI->>API: sessionId + query + contextSet
	API->>Graph: Validate context and resolve inputs
	alt Unsupported context or unavailable specialist
		Graph-->>API: Structured compatibility error
		API-->>UI: Actionable rejection
	else Supported indexed single-image context
		Graph->>Specialist: Execute task-shaped instruction
		Specialist-->>Graph: Text or grounding observation
		Graph-->>API: Composed answer and evidence
		API-->>UI: Answer, confidence, trace, report URL
	end
```

## 4. Single-Image Flow Available Now

For an indexed single patch, the user experience is:

1. Select a patch and choose the default optical view or full optical-plus-SAR
   bands.
2. Ask a VQA, captioning, or grounding question.
3. The orchestrator selects the ready EOCaptioner tool and formats the
   instruction into the specialist's supported shape.
4. The specialist returns text or normalized bounding-box coordinates.
5. The interface displays the answer; coordinate output becomes visual bbox
   evidence linked to the patch.

```mermaid
flowchart LR
	Patch[Indexed optical patch] --> Query[Caption, VQA, or grounding question]
	Query --> Agent[Gemma 4 orchestrator]
	Agent --> Template[Specialist task template]
	Template --> EO[EOCaptioner]
	EO --> Raw[Text or normalized coordinates]
	Raw --> Answer[Readable answer]
	Raw --> Overlay[Bounding-box evidence when coordinates are present]
	Answer & Overlay --> UI[Chat and map presentation]
```

The user does not need to know archive paths or model-specific prompt syntax;
those are handled behind the API and specialist contract.

## 5. Bi-Temporal Flow

The intended user journey is to open the temporal browser, choose two captures
for one location, select a change question, and submit the pair. The context
and UI affordances exist for this workflow, and the BiTemporal specialist is
implemented and evaluated in its own workstream. However, the orchestrator's
current capability registry marks the change-detection tool as not ready.

```mermaid
flowchart TD
	Location[Choose one map location] --> Dates[Review available timestamps]
	Dates --> T1[Add capture t1]
	Dates --> T2[Add capture t2]
	T1 & T2 --> Pair[Bi-temporal context]
	Pair --> Question[Ask change question]
	Question --> Gate{Change tool ready in registry?}
	Gate -->|Current build: no| Rejected[Explain unsupported task]
	Gate -->|When integrated| Delta[DeltaVLM / BiTemporal specialist]
	Delta --> ChangeAnswer[Change answer and temporal evidence]
```

The user-facing behavior for the current build is an explicit structured
rejection. It does not fabricate a change map or route the pair through the
single-image model.

## 6. Optical-SAR Flow

The intended cross-modal journey is to provide co-located optical and SAR
imagery, choose a fusion question, and inspect a fused answer. The context
contract and the TerraFM fusion decision are documented, but the fusion tool is
not currently ready in the registry.

```mermaid
flowchart TD
	Optical[Optical capture] --> Pair[Co-located optical + SAR context]
	SAR[SAR capture] --> Pair
	Pair --> Question[Ask joint sensor question]
	Question --> Gate{Fusion tool ready in registry?}
	Gate -->|Current build: no| Rejected[Explain unsupported task]
	Gate -->|When integrated| Fusion[TerraFM fusion specialist]
	Fusion --> Answer[Fused multisensor answer]
	Answer --> UI[Chat and visual evidence]
```

The current ready single-image path can accept optional SAR alongside optical
bands, but it does not constitute the separate cross-modal fusion capability.
SAR-only input is rejected because the ready specialist requires optical input.

## 7. Progress, Trace, And Results

While a supported query runs, the frontend can subscribe to the session
activity stream. The backend reports meaningful stages such as compatibility
checking, patch resolution, agent steps, tool execution, observation results,
validation, and response composition. The same events are logged server-side.

```mermaid
sequenceDiagram
	participant UI as Activity panel
	participant SSE as Session activity stream
	participant Graph as Query graph
	participant Store as Session/report store

	UI->>SSE: Subscribe for session activity
	Graph-->>SSE: compatibility and resolution status
	Graph-->>SSE: agent and specialist execution status
	Graph-->>SSE: observation validation status
	Graph->>Store: Persist assistant message and report
	Graph-->>SSE: done event
	UI->>Store: Open execution trace or report URL
```

Each successful assistant result can contain:

- natural-language answer;
- spatial evidence when the specialist response contains parseable grounding
  coordinates;
- confidence value from the response contract;
- execution trace with task, models used, and tool-call parameters; and
- a downloadable persisted JSON report.

The current response path does not provide reliable text-span grounding, and a
failed or unsupported operation is shown as an error rather than an apparently
successful visual result.

## 8. Session Continuity

Sessions are created and loaded through the session API. Context sets and chat
messages are persisted in SQLite, allowing the user to return to a previous
analysis. Reports are written when a query completes, so the result shown in a
download remains tied to the answer, evidence, confidence, and trace produced
for that turn.

## 9. Related Documentation

- [01-system-design.md](01-system-design.md): system architecture.
- [02-technical-approach.md](02-technical-approach.md): internal execution and
  data path.
- [05-datasets.md](05-datasets.md): dataset and split responsibilities.
- [ADR 0002](adr/0002-single-image-model-choice.md) through [ADR 0005](adr/0005-segmentation-model-choice.md): specialist decisions.
