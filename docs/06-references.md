# References

This page is the source index for SatQuery AI. It lists the papers, datasets,
models, frameworks, and standards that are used by the repository or named by
an adopted ADR. Technical explanations and evaluation decisions remain in the
linked documentation; this page avoids repeating them.

## 1. Project Documentation And Decisions

| Reference | Use in the project |
| --- | --- |
| [01-system-design.md](01-system-design.md) | System boundary, components, orchestration flow, and response artifacts. |
| [02-technical-approach.md](02-technical-approach.md) | Internal request, data, model-serving, validation, and integration paths. |
| [03-models-and-metrics.md](03-models-and-metrics.md) | Model roles, evaluation evidence, and metric mapping. |
| [05-datasets.md](05-datasets.md) | Dataset inventory and provenance notes. |
| [07-feasibility-viability.md](07-feasibility-viability.md) | Feasibility evidence and current integration boundaries. |
| [09-deployment.md](09-deployment.md) | Deployment and service-boundary guidance. |
| [ADR 0001](adr/0001-orchestrator-choice.md) | Gemma 4 E2B and LangGraph orchestration decision. |
| [ADR 0002](adr/0002-single-image-model-choice.md) | TinyRS-R1 single-image VQA, captioning, and grounding decision. |
| [ADR 0003](adr/0003-fusion-encoder-choice.md) | TerraFM optical-SAR fusion decision. |
| [ADR 0004](adr/0004-change-detection-architecture.md) | DeltaVLM / BiTemporal v2 change-understanding decision. |
| [ADR 0005](adr/0005-segmentation-model-choice.md) | SAM and TerraFM-UperNet segmentation decision. |

## 2. Remote-Sensing Models And Papers

### Single-image understanding

- **TinyRS-R1:** Aybora et al., *TinyRS: Thinking Small in Remote Sensing
	Foundation Models*, 2025. [arXiv:2505.12099](https://arxiv.org/abs/2505.12099)
- **Qwen2-VL:** *Qwen2-VL: Enhancing Vision-Language Model's Perception of the
	World at Any Resolution*, 2024. [arXiv:2409.12191](https://arxiv.org/abs/2409.12191)

### Earth-observation representation and optical-SAR fusion

- **TerraFM:** *TerraFM: An Earth Observation Foundation Model for Multisensor
	Remote Sensing*, 2025. [arXiv:2506.06281](https://arxiv.org/abs/2506.06281)
- **CROMA:** Anthony et al., *CROMA: Remote Sensing Representations with
	Contrastive Radar-Optical Masked Autoencoders*, 2023. Referenced as the
	comparative optical-SAR representation baseline in [ADR 0003](adr/0003-fusion-encoder-choice.md).
- **Gated-guided fusion:** optical-SAR gated fusion reference cited by [ADR 0003](adr/0003-fusion-encoder-choice.md).

### Bi-temporal change understanding

- **DeltaVLM:** *DeltaVLM: Efficient Instruction-Guided Difference Perception
	for Change-VQA*, *Remote Sensing*, 2025. Chosen in [ADR 0004](adr/0004-change-detection-architecture.md).
- **TCSSM:** *TCSSM: Text-Conditioned State-Space Modeling for
	Domain-Generalized Change-VQA*, 2025. [arXiv:2508.08974](https://arxiv.org/abs/2508.08974)
- **DARFT:** *DARFT: Robustifying Change Detection Visual Question Answering
	via SFT and GRPO*, 2025. [arXiv:2512.24591](https://arxiv.org/abs/2512.24591)

### Segmentation

- **SAM:** Kirillov et al., *Segment Anything*, ICCV 2023.
	[arXiv:2304.02643](https://arxiv.org/abs/2304.02643)
- **UperNet:** Xiao et al., *Unified Perceptual Parsing for Scene
	Understanding*, ECCV 2018. [arXiv:1807.10221](https://arxiv.org/abs/1807.10221)
- **MM-OVSeg:** multimodal optical-SAR open-vocabulary segmentation reference
	cited by [ADR 0005](adr/0005-segmentation-model-choice.md).

## 3. Datasets And Benchmarks

| Dataset or benchmark | Relevance | Authoritative source or project reference |
| --- | --- | --- |
| **BigEarthNet** | Indexed Sentinel-1 and Sentinel-2 patch data used by the repository's patch and serving pipeline. | [BigEarthNet project](https://bigearth.net/) and the repository's `BigEarthNet-*.zip` data contract. |
| **BigEarthNet-S1/S2 paired data** | Optical and SAR modality pairing used for patch resolution and the fusion design. | [ADR 0003](adr/0003-fusion-encoder-choice.md). |
| **CDVQA / SECOND-derived data** | Bi-temporal question-answer data used by `BiTemporal/src/dataset.py`, training, and evaluation. | [ADR 0004](adr/0004-change-detection-architecture.md) and [BiTemporal/readme.md](../BiTemporal/readme.md). |
| **VRSBench** | VQA, detailed captioning, and object grounding benchmark for single-image remote sensing. | [arXiv:2406.12384](https://arxiv.org/abs/2406.12384) and [ADR 0002](adr/0002-single-image-model-choice.md). |
| **RSVQA** | Remote-sensing VQA for presence/absence, counting, and comparison. | [RSVQA project](https://rsvqa.sylvainlobry.com/) and [ADR 0002](adr/0002-single-image-model-choice.md). |
| **CORINE Land Cover** | Thematic land-cover taxonomy for the selected TerraFM-UperNet segmentation path. | [Copernicus Land Monitoring Service](https://land.copernicus.eu/en/products/corine-land-cover) and [ADR 0005](adr/0005-segmentation-model-choice.md). |

The repository records a local BiTemporal evaluation result in
[03-models-and-metrics.md](03-models-and-metrics.md); it does not record local
VRSBench, RSVQA, fusion, or segmentation scores.

## 4. Frameworks And Runtime Components

These are the principal implementation technologies visible in the repository:

| Component | Project source | Role in SatQuery AI |
| --- | --- | --- |
| **Python** | [python.org](https://www.python.org/) | Backend, data, training, and evaluation language. |
| **FastAPI** | [fastapi.tiangolo.com](https://fastapi.tiangolo.com/) | HTTP API and model-service boundaries. |
| **LangGraph** | [LangGraph documentation](https://langchain-ai.github.io/langgraph/) | StateGraph orchestration and controlled tool loop. |
| **LangChain Core** | [LangChain documentation](https://python.langchain.com/) | Messages, tool schemas, and model abstraction primitives. |
| **PyTorch** | [pytorch.org](https://pytorch.org/) | Tensor execution, training, and offline specialist inference. |
| **Hugging Face Transformers** | [Transformers documentation](https://huggingface.co/docs/transformers/index) | Language-model loading, tokenization, and generation. |
| **PEFT / LoRA** | [PEFT documentation](https://huggingface.co/docs/peft/index) | Parameter-efficient adaptation in the BiTemporal workstream. |
| **bitsandbytes** | [bitsandbytes repository](https://github.com/bitsandbytes-foundation/bitsandbytes) | Quantized language-model loading and optimizer support in the BiTemporal workstream. |
| **Rasterio** | [rasterio.readthedocs.io](https://rasterio.readthedocs.io/) | GeoTIFF reading and raster preparation. |
| **Docker Compose** | [Docker Compose documentation](https://docs.docker.com/compose/) | Separate UI, orchestrator, main-model, and specialist services. |
| **React and Vite** | [react.dev](https://react.dev/) and [vite.dev](https://vite.dev/) | Web application and frontend build system. |
| **MapLibre GL JS** | [maplibre.org](https://maplibre.org/) | Map workspace and geographic context in the frontend design. |

## 5. Data And Geospatial Standards

- **GeoTIFF:** raster input and band storage format used by the data and model
	serving paths. [OGC GeoTIFF Standard](https://www.ogc.org/standard/geotiff/)
- **GeoJSON:** geographic feature and polygon representation used by the
	frontend/API contracts. [RFC 7946](https://www.rfc-editor.org/rfc/rfc7946)
- **Sentinel-1 and Sentinel-2:** the SAR and optical Earth-observation sources
	represented in the repository's BigEarthNet patch archives. [Copernicus
	Sentinel data access](https://dataspace.copernicus.eu/)

## 6. Reference Use Policy

The project should cite the original paper, dataset owner, or official
framework documentation when reporting a model or result. ADRs remain the
authoritative record for why a model was selected; this page records where the
underlying work can be found. A reference listed here does not imply that its
corresponding specialist is currently enabled in the query registry.
