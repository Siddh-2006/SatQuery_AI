# BiTemporal v2

A specialized bi-temporal remote-sensing vision-language model for answering questions about **changes between two satellite images acquired at different times**.

BiTemporal v2 is designed as a specialist model for the SatQuery AI ecosystem. It processes a pair of satellite images, learns their temporal difference, conditions that difference representation on the user's question, and generates a natural-language answer using a quantized TinyRS-R1 language model with LoRA fine-tuning.

---

## 1. Overview

Traditional image-understanding models generally analyze a single image.

BiTemporal v2 instead focuses on the **temporal dimension**:

> Given satellite images of the same geographical region at two different times, determine what changed, how it changed, and answer questions about those changes.

The model is designed to handle questions such as:

- Did anything change?
- Did a particular object or region increase or decrease?
- What changed?
- What type of change occurred?
- What is the change ratio?
- Which region/object experienced the largest change?
- Which experienced the smallest change?

The system combines a frozen remote-sensing vision backbone with temporal-difference modeling and parameter-efficient language-model adaptation.

---

## 2. Architecture

```text
                Satellite Image t1
                       │
                       ▼
                 ┌──────────┐
                 │ TerraFM  │
                 └────┬─────┘
                      │
                Vision Features
                      │
                      │
                ┌─────┴─────┐
                │           │
                ▼           ▼
          Image t1      Image t2
                │           │
                └─────┬─────┘
                      │
                      ▼
                ┌────────────┐
                │ DeltaBlock │
                └─────┬──────┘
                      │
              Temporal Difference
                      │
                      ▼
                ┌────────────┐
                │   TCSSM    │◄──────── Question Embedding
                └─────┬──────┘
                      │
             Question-conditioned
             temporal representation
                      │
                      ▼
              ┌───────────────┐
              │FusionProjector│
              └───────┬───────┘
                      │
                Vision Tokens
                      │
                      ▼
          ┌────────────────────────┐
          │       TinyRS-R1        │
          │   Qwen2-VL backbone    │
          │                        │
          │   + LoRA adapters      │
          └───────────┬────────────┘
                      │
                      ▼
                 Text Answer
```

### Core pipeline

```text
TerraFM
   ↓
Temporal Difference (DeltaBlock)
   ↓
Question-Conditioned Temporal State Modeling (TCSSM)
   ↓
FusionProjector
   ↓
TinyRS-R1 + LoRA
   ↓
Answer
```

---

## 3. Components

### 3.1 TerraFM

TerraFM is the remote-sensing visual encoder.

It extracts spatial features from each satellite image independently.

For each image:

```text
Image → TerraFM → 197 vision tokens × 768 dimensions
```

The TerraFM backbone is kept **frozen during training**.

This preserves the pretrained remote-sensing representation while allowing the temporal and language components to specialize for change-question answering.

---

### 3.2 DeltaBlock

The two TerraFM representations are passed into the DeltaBlock.

It models temporal change using two complementary signals:

1. Direct feature subtraction
2. Cross-attention between the second-time-step representation and the first-time-step representation

Conceptually:

```text
Difference = Features(t2) - Features(t1)

Cross-attention = Attention(Features(t2), Features(t1), Features(t1))
```

These representations are concatenated and projected back into the vision embedding dimension.

This allows the model to represent both:

- explicit feature differences
- relationships between the two temporal observations

---

### 3.3 TCSSM

**TCSSM — Text-Conditioned State-Space Modeling**

TCSSM incorporates the user's question into the temporal representation.

The question embedding is used to predict a feature-wise gating mechanism that controls how temporal information is accumulated across the vision-token sequence.

Conceptually:

```text
Temporal Difference
        +
Question Representation
        ↓
Question-conditioned gating
        ↓
Temporal state sequence
```

This allows different questions to focus on different aspects of the same temporal change representation.

For example, the same image pair can be queried with:

```text
"Did anything increase?"
```

or:

```text
"Which region experienced the largest change?"
```

while using the same underlying image pair.

---

### 3.4 FusionProjector

The TCSSM representation has dimension 768, while TinyRS-R1 uses a hidden dimension of 1536.

The FusionProjector maps:

```text
768 → 1536
```

so that the temporal vision features can be supplied to the language model as compatible vision tokens.

---

### 3.5 TinyRS-R1

TinyRS-R1 provides the language-generation component.

The model uses:

- 4-bit quantization
- NF4 quantization
- float16 quantized computation
- hidden dimension: 1536

The base language model is largely frozen.

---

### 3.6 LoRA

Instead of updating the entire language model, BiTemporal v2 uses **Low-Rank Adaptation (LoRA)**.

Configuration:

```yaml
r: 16
alpha: 32
dropout: 0.05

target_modules:
  - q_proj
  - v_proj
```

Only approximately **2.18 million parameters** are trainable compared with approximately **2.21 billion total parameters**.

This makes fine-tuning substantially more memory-efficient.

---

## 4. Dataset

The model was trained on a cleaned bi-temporal remote-sensing question-answering dataset.

### Dataset statistics

| Property | Value |
|---|---:|
| Total Q&A samples | 65,967 |
| Unique image pairs | 25,563 |
| Average Q&A per image pair | 2.58 |
| Minimum Q&A per pair | 1 |
| Maximum Q&A per pair | 6 |
| Question types | 8 |
| Required unique image filenames | 1,600 |
| Available complete image pairs | 1,600 |

Each sample contains:

```text
pair_id
question
answer
```

The question contains:

```text
img_id
question
type
```

Images are loaded as RGB images, resized to `224 × 224`, and normalized using ImageNet normalization.

---

## 5. Question Types

The dataset contains eight question categories:

| Question Type | Description |
|---|---|
| `change_or_not` | Whether a change occurred |
| `increase_or_not` | Whether the relevant quantity increased |
| `decrease_or_not` | Whether the relevant quantity decreased |
| `change_to_what` | What the changed region/object became |
| `change_ratio` | Quantitative change ratio |
| `change_ratio_types` | Type/category of change based on ratio |
| `largest_change` | Which candidate experienced the largest change |
| `smallest_change` | Which candidate experienced the smallest change |

---

## 6. Training

### Training configuration

```yaml
batch_size: 4
num_epochs: 3
gradient_accumulation_steps: 1

learning_rate: 3.0e-5
weight_decay: 0.01
adam_eps: 1.0e-4

scheduler: cosine
min_learning_rate: 1.0e-6
```

### LoRA configuration

```yaml
r: 16
alpha: 32
dropout: 0.05

target_modules:
  - q_proj
  - v_proj
```

### Image configuration

```yaml
image_size: 224
```

### Evaluation configuration

```yaml
max_new_tokens: 16
max_samples_per_question_type: 150
```

---

## 7. Training Strategy

The training objective combines the temporal vision representation with the question and target answer.

The input sequence to the language model contains:

```text
[Temporal Vision Tokens]
        +
[Question Tokens]
        +
[Target Answer Tokens]
```

Loss is calculated on the answer tokens while the vision and prompt portions are masked from the language-model loss.

This enables the model to learn:

```text
Two satellite images
        +
Question
        ↓
Temporal understanding
        ↓
Answer generation
```

---

## 8. Parameter Training

### Frozen

- TerraFM backbone
- Base TinyRS-R1 model parameters

### Trainable

- DeltaBlock
- TCSSM
- FusionProjector
- LoRA adapters

```text
Total parameters       ≈ 2.211B
Trainable parameters   ≈ 2.179M
```

Only about **0.1% of the total model parameters** are trainable.

---

## 9. Checkpointing and Resume

Training supports automatic checkpoint recovery.

Checkpoints are written periodically during training and at the end of each epoch.

Important artifacts include:

```text
checkpoints/
├── checkpoint_epoch_3.pt
├── latest.pt
└── tinyrs_r1_lora_epoch_3/
```

The latest checkpoint can be used to resume training without starting from the beginning.

---

## 10. Final Training Run

The final training run completed successfully.

### Training statistics

```text
Epochs:                  3
Micro-batches:           49,473
Optimizer steps:         49,473
Final average loss:      0.1501
```

The run started at:

```text
Sun Sep 6 07:09:33 PM IST 2026
```

and finished at:

```text
Sun Sep 6 11:34:32 PM IST 2026
```

Total wall-clock training time was approximately **4 hours 25 minutes**.

---

## 11. H100 Performance Benchmark

The model was benchmarked on an NVIDIA H100 NVL.

| Batch Size | Samples/sec | Peak GPU Memory |
|---:|---:|---:|
| 1 | 4.54 | 2.23 GB |
| 2 | 9.14 | 2.71 GB |
| 4 | 18.04 | 3.63 GB |
| 8 | 36.22 | 5.56 GB |

Batch size **4** was selected for the final training configuration.

The measured full training iteration at batch size 4 was approximately **0.222 seconds**, with approximately **3.63 GB peak GPU memory**.

---

## 12. Evaluation

The final model was evaluated on a **balanced 400-sample evaluation set**:

```text
50 samples × 8 question types = 400 samples
```

### Overall performance

```text
Correct: 233 / 400
Accuracy: 58.25%
```

### Per-question-type performance

| Question Type | Correct | Accuracy |
|---|---:|---:|
| `change_or_not` | 42/50 | **84%** |
| `decrease_or_not` | 41/50 | **82%** |
| `increase_or_not` | 40/50 | **80%** |
| `change_ratio_types` | 36/50 | **72%** |
| `change_to_what` | 30/50 | **60%** |
| `largest_change` | 20/50 | **40%** |
| `change_ratio` | 13/50 | **26%** |
| `smallest_change` | 11/50 | **22%** |

### Interpretation

The evaluation indicates that the current model is strongest at **qualitative and directional change detection**.

It performs well on:

```text
Did something change?
Did something increase?
Did something decrease?
```

The more difficult categories are quantitative and comparative reasoning tasks, particularly:

```text
change_ratio
smallest_change
largest_change
```

This suggests that the current model has developed useful temporal-change representations but still has room for improvement in precise numerical and cross-candidate comparison reasoning.

---

## 13. Verification Tests

The implementation includes dedicated tests for the main training components.

### Forward test

`test_forward.py`

Verifies that the complete model pipeline produces valid tensors through:

```text
TerraFM
→ DeltaBlock
→ TCSSM
→ FusionProjector
→ TinyRS-R1
```

Expected vision representation:

```text
[batch, 197, 768]
```

Expected projected representation:

```text
[batch, 197, 1536]
```

### Backward test

`test_backward.py`

Verifies gradient flow through the trainable components.

The test confirms gradients reach:

- DeltaBlock
- TCSSM
- FusionProjector
- LoRA adapters

while TerraFM remains frozen.

### Optimizer test

`test_optimizer.py`

Verifies that an optimization step actually updates trainable model parameters.

---

## 14. Repository Structure

```text
BiTemporal/
│
├── configs/
│   └── config.yaml
│
├── src/
│   ├── model.py
│   ├── dataset.py
│   ├── train.py
│   ├── evaluate.py
│   ├── test_forward.py
│   ├── test_backward.py
│   └── test_optimizer.py
│
└── README.md
```

The repository intentionally contains the **source implementation and configuration**, rather than large datasets and model weights.

---

## 15. Important Model/Data Artifacts

The following artifacts are required for a complete training/evaluation environment but are not intended to be committed to Git:

```text
data/
models/
checkpoints/
logs/
runs/
```

These include:

- satellite image data
- processed parquet datasets
- annotations
- TerraFM weights
- TinyRS-R1 model files
- training checkpoints
- experiment logs

Large model/data artifacts should therefore be provisioned separately on the target machine.

---

## 16. Configuration

All important paths and hyperparameters are centralized in:

```text
configs/config.yaml
```

The configuration specifies:

```text
Dataset paths
Image root
TerraFM weights
TinyRS-R1 model directory
Checkpoint directory
Log directory

Training hyperparameters
LoRA configuration
Image size
Evaluation limits
```

This avoids hard-coding experiment-specific paths throughout the source code.

---

## 17. Environment

The final implementation was developed and tested in a CUDA-enabled Python environment.

Key package versions:

```text
torch==2.14.0+cu130
torchvision==0.29.0+cu130
timm==1.0.29

transformers==5.16.1
peft==0.20.0
bitsandbytes==0.50.2
accelerate==1.14.0

Pillow
pandas==3.0.5
pyarrow==25.0.1
PyYAML==6.0.3
```

The final training run was performed on an NVIDIA H100 NVL.

---

## 18. Running the Project

### Activate the environment

```bash
eval "$(/apps/compilers/anaconda3-2024.06/bin/conda shell.bash hook)"
conda activate My_model
```

### Run the forward test

```bash
python3 src/test_forward.py
```

### Run the backward test

```bash
python3 src/test_backward.py
```

### Run the optimizer test

```bash
python3 src/test_optimizer.py
```

### Train

```bash
python3 src/train.py
```

Training reads its configuration from:

```text
configs/config.yaml
```

and automatically resumes from available checkpoints when configured to do so.

### Evaluate

```bash
python3 src/evaluate.py
```

---

## 19. Relationship to SatQuery AI

BiTemporal v2 is intended to function as a **specialist model within SatQuery AI**.

It does not replace the existing EOCaptioner.

The two models serve different purposes.

### EOCaptioner

```text
Satellite Image
      ↓
TerraFM
      ↓
Vision-Language Projection
      ↓
Qwen2
      ↓
Caption / image understanding
```

### BiTemporal

```text
Satellite Image t1 ─┐
                    ├→ TerraFM → DeltaBlock → TCSSM
Satellite Image t2 ─┘                           ↓
                                           FusionProjector
                                                ↓
                                         TinyRS-R1 + LoRA
                                                ↓
                                             Answer
```

BiTemporal therefore acts as a **temporal-change reasoning specialist**, while EOCaptioner remains responsible for its existing single-image understanding capabilities.

---

## 20. Planned Integration

The intended integration path is:

```text
                    SatQuery AI
                         │
                    Orchestrator
                         │
              ┌──────────┴──────────┐
              │                     │
        EOCaptioner            BiTemporal
        Specialist             Specialist
              │                     │
       Single-image             Bi-temporal
       understanding             reasoning
```

BiTemporal can subsequently be exposed to the SatQuery AI orchestrator as a dedicated specialist/tool.

The integration should preserve the existing EOCaptioner implementation rather than replacing it.

---

## 21. Current Status

### Completed

- [x] Dataset preparation
- [x] Image-pair verification
- [x] TerraFM integration
- [x] DeltaBlock implementation
- [x] TCSSM implementation
- [x] FusionProjector implementation
- [x] TinyRS-R1 integration
- [x] 4-bit quantization
- [x] LoRA fine-tuning
- [x] Forward-pass verification
- [x] Backward-pass verification
- [x] Optimizer verification
- [x] H100 performance benchmarking
- [x] Full 3-epoch training
- [x] Checkpoint generation
- [x] Balanced evaluation
- [x] SatQuery AI integration-ready source organization

### Current result

```text
Training:
3 epochs
49,473 optimizer steps
Final average loss: 0.1501

Evaluation:
233 / 400
58.25% accuracy
```

---

## 22. Future Improvements

The current evaluation suggests that future work should focus particularly on:

- quantitative change-ratio reasoning
- largest/smallest change comparisons
- more precise numerical answer generation
- improved cross-candidate comparison
- stronger temporal reasoning
- broader evaluation sets
- integration into the SatQuery AI orchestrator
- end-to-end inference testing inside the SatQuery AI application

The existing trained checkpoint should be preserved as the current baseline before attempting further training experiments.

---

## 23. Summary

BiTemporal v2 introduces a dedicated temporal reasoning pipeline for satellite-image question answering:

```text
Two Satellite Images
        ↓
      TerraFM
        ↓
   DeltaBlock
        ↓
      TCSSM
        ↓
 FusionProjector
        ↓
 TinyRS-R1 + LoRA
        ↓
   Natural-Language Answer
```

The model successfully completed full training on an H100 NVL with a final training loss of **0.1501** and achieved **58.25% accuracy on a balanced 400-sample evaluation set**.

Its strongest capability is qualitative/directional change detection, while quantitative and comparative reasoning remain the primary areas for further improvement.

BiTemporal v2 is ready to serve as the **bi-temporal change-reasoning specialist** for the next stage of SatQuery AI integration.
