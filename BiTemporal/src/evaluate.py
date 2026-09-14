import os
import json
import yaml
import torch
import pandas as pd

from PIL import Image
from torchvision import transforms

from model import BiTemporalModel


# ============================================================
# Configuration
# ============================================================

CONFIG_PATH = "configs/config.yaml"

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)


TRAIN_PARQUET = config["paths"]["train_parquet"]
VAL_PARQUET = config["paths"]["val_parquet"]
ANNOTATIONS_PATH = config["paths"]["annotations"]
IMAGE_ROOT = config["paths"]["image_root"]

CHECKPOINT_DIR = config["paths"]["checkpoint_dir"]

MODEL_CHECKPOINT = os.path.join(
    CHECKPOINT_DIR,
    "checkpoint_epoch_3.pt"
)

LORA_CHECKPOINT = os.path.join(
    CHECKPOINT_DIR,
    "tinyrs_r1_lora_epoch_3"
)

MAX_NEW_TOKENS = config["evaluation"]["max_new_tokens"]

MAX_SAMPLES_PER_QUESTION_TYPE = config["evaluation"][
    "max_samples_per_question_type"
]


# ============================================================
# Safety limit
# ============================================================

# Evaluate 80 samples total.
# The samples are distributed equally across all question types.
MAX_EVAL_SAMPLES =  400


# ============================================================
# Device
# ============================================================

device = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)


print("=" * 60)
print("BiTemporal v2 Evaluation")
print("=" * 60)

print(f"Device: {device}")

if torch.cuda.is_available():
    print(
        f"GPU: {torch.cuda.get_device_name(0)}"
    )


# ============================================================
# Load validation data
# ============================================================

print("\nLoading validation data...")

val_df = pd.read_parquet(
    VAL_PARQUET
)

val_df["q_type"] = val_df["question"].apply(
    lambda q: q.get("type", "unknown")
    if isinstance(q, dict)
    else "unknown"
)

val_df["a_text"] = val_df["answer"].apply(
    lambda a: str(
        a.get("answer", "")
    ).strip().lower()
    if isinstance(a, dict)
    else str(a).strip().lower()
)

print(
    f"Validation samples: {len(val_df)}"
)


# ============================================================
# Stratified evaluation sampling
# ============================================================

print("\nCreating stratified evaluation sample...")

# ------------------------------------------------------------
# We explicitly sample each question type rather than using
# groupby().apply(), because some pandas versions can remove
# the grouping column from the resulting dataframe.
# ------------------------------------------------------------

sampled_groups = []

for q_type, group in val_df.groupby(
    "q_type",
    sort=False
):

    n_samples = min(
        len(group),
        MAX_SAMPLES_PER_QUESTION_TYPE
    )

    sampled_group = group.sample(
        n=n_samples,
        random_state=1
    )

    sampled_groups.append(
        sampled_group
    )


eval_sample = pd.concat(
    sampled_groups,
    ignore_index=True
)


print(
    f"Stratified evaluation samples: "
    f"{len(eval_sample)}"
)

print("\nSamples per question type:")

print(
    eval_sample["q_type"].value_counts()
)


# ============================================================
# Apply stratified safety limit
# ============================================================

if MAX_EVAL_SAMPLES is not None:

    question_types = eval_sample["q_type"].unique()

    samples_per_type = MAX_EVAL_SAMPLES // len(question_types)

    stratified_limited_groups = []

    for q_type in question_types:

        group = eval_sample[
            eval_sample["q_type"] == q_type
        ]

        n_samples = min(
            len(group),
            samples_per_type
        )

        stratified_limited_groups.append(
            group.sample(
                n=n_samples,
                random_state=1
            )
        )

    eval_sample = pd.concat(
        stratified_limited_groups,
        ignore_index=True
    )

    # Shuffle the final evaluation set so that
    # question types are not evaluated in blocks.
    eval_sample = eval_sample.sample(
        frac=1,
        random_state=1
    ).reset_index(drop=True)


print(
    f"\nActual samples to evaluate: "
    f"{len(eval_sample)}"
)

print("\nFinal samples per question type:")

print(
    eval_sample["q_type"].value_counts()
)


# ============================================================
# Build answer vocabulary
# ============================================================

print("\nBuilding answer vocabulary...")

train_df = pd.read_parquet(
    TRAIN_PARQUET
)

answer_vocab = set(
    train_df["answer"].apply(
        lambda a: str(
            a.get("answer", "")
        ).strip().lower()
        if isinstance(a, dict)
        else str(a).strip().lower()
    )
)

answer_vocab = sorted(
    answer_vocab
)

print(
    f"Answer vocabulary size: "
    f"{len(answer_vocab)}"
)


# ============================================================
# Image annotation mapping
# ============================================================

print("\nLoading image annotations...")

with open(
    ANNOTATIONS_PATH,
    "r"
) as f:

    annotations = json.load(f)


image_map = {
    int(img["id"]): img["file_name"]
    for img in annotations["images"]
}


print(
    f"Annotated images: "
    f"{len(image_map)}"
)


# ============================================================
# Image transform
# ============================================================

transform = transforms.Compose([

    transforms.Resize(
        (224, 224)
    ),

    transforms.ToTensor(),

    transforms.Normalize(
        mean=[
            0.485,
            0.456,
            0.406
        ],

        std=[
            0.229,
            0.224,
            0.225
        ]
    ),
])


# ============================================================
# Image loading
# ============================================================

def load_image_pair(img_id):

    if img_id not in image_map:

        raise KeyError(
            f"Image ID {img_id} "
            f"not found in annotations."
        )

    filename = image_map[img_id]

    im1_path = os.path.join(
        IMAGE_ROOT,
        "im1",
        filename
    )

    im2_path = os.path.join(
        IMAGE_ROOT,
        "im2",
        filename
    )

    if not os.path.exists(im1_path):

        raise FileNotFoundError(
            im1_path
        )

    if not os.path.exists(im2_path):

        raise FileNotFoundError(
            im2_path
        )

    im1 = Image.open(
        im1_path
    ).convert("RGB")

    im2 = Image.open(
        im2_path
    ).convert("RGB")

    im1 = transform(
        im1
    ).unsqueeze(0)

    im2 = transform(
        im2
    ).unsqueeze(0)

    return (
        im1.to(device),
        im2.to(device)
    )


# ============================================================
# Answer extraction
# ============================================================

def extract_answer_v2(
    generated_text,
    valid_answers
):

    clean = generated_text.replace(
        "<|im_end|>",
        ""
    ).strip().lower()

    # --------------------------------------------------------
    # Exact match
    # --------------------------------------------------------

    for ans in valid_answers:

        if clean == ans:

            return ans

    # --------------------------------------------------------
    # Answer appears inside generated text
    # --------------------------------------------------------

    for ans in sorted(
        valid_answers,
        key=len,
        reverse=True
    ):

        if ans in clean:

            return ans

    # --------------------------------------------------------
    # Fallback
    # --------------------------------------------------------

    return clean.split(
        "\n"
    )[-1].strip()


# ============================================================
# Load BiTemporal v2 model
# ============================================================

print("\n" + "=" * 60)
print("Loading BiTemporal v2 model")
print("=" * 60)


model = BiTemporalModel(
    terrafm_weights=config["paths"][
        "terrafm_weights"
    ],

    llm_dir=config["paths"][
        "llm_dir"
    ],
)


# ============================================================
# Load trained BiTemporal modules
# ============================================================

print(
    "\nLoading trained BiTemporal modules..."
)


if not os.path.exists(
    MODEL_CHECKPOINT
):

    raise FileNotFoundError(
        "Model checkpoint not found:\n"
        f"{MODEL_CHECKPOINT}"
    )


checkpoint = torch.load(
    MODEL_CHECKPOINT,
    map_location="cpu"
)

model_state = checkpoint[
    "model_state"
]


# ------------------------------------------------------------
# FusionProjector
# ------------------------------------------------------------

model.projector.load_state_dict(
    model_state["projector"]
)


# ------------------------------------------------------------
# DeltaBlock
# ------------------------------------------------------------

model.delta_block.load_state_dict(
    model_state["delta_block"]
)


# ------------------------------------------------------------
# TCSSM
# ------------------------------------------------------------

model.tcssm_layer.load_state_dict(
    model_state["tcssm_layer"]
)


# ------------------------------------------------------------
# RGB vision stem
# ------------------------------------------------------------

model.flexible_stem_rgb.load_state_dict(
    model_state["vision_stem"]
)


print("Projector loaded.")
print("DeltaBlock loaded.")
print("TCSSM loaded.")
print("RGB vision stem loaded.")

print(
    f"Checkpoint epoch: "
    f"{checkpoint.get('epoch', 'unknown')}"
)

print(
    f"Checkpoint global step: "
    f"{checkpoint.get('global_step', 'unknown')}"
)


# ============================================================
# Load trained LoRA adapter
# ============================================================

print(
    "\n" + "=" * 60
)

print(
    "Loading trained LoRA adapter"
)

print(
    "=" * 60
)


if not os.path.isdir(
    LORA_CHECKPOINT
):

    raise FileNotFoundError(
        "LoRA checkpoint directory not found:\n"
        f"{LORA_CHECKPOINT}"
    )


adapter_config = os.path.join(
    LORA_CHECKPOINT,
    "adapter_config.json"
)

adapter_weights = os.path.join(
    LORA_CHECKPOINT,
    "adapter_model.safetensors"
)


if not os.path.exists(
    adapter_config
):

    raise FileNotFoundError(
        "LoRA adapter_config.json "
        "not found:\n"
        f"{adapter_config}"
    )


if not os.path.exists(
    adapter_weights
):

    raise FileNotFoundError(
        "LoRA adapter_model.safetensors "
        "not found:\n"
        f"{adapter_weights}"
    )


print(
    f"LoRA directory: "
    f"{LORA_CHECKPOINT}"
)


# ------------------------------------------------------------
# BiTemporalModel already creates the PEFT/LoRA model.
#
# Therefore we load the trained adapter weights into the
# existing PEFT model instead of creating another LoRA layer.
# ------------------------------------------------------------

model.llm.load_adapter(
    LORA_CHECKPOINT,
    adapter_name="default"
)


print(
    "Trained LoRA adapter loaded successfully."
)


# ============================================================
# Evaluation mode
# ============================================================

model.eval()

model.llm.eval()

model.projector.eval()

model.delta_block.eval()

model.tcssm_layer.eval()

model.flexible_stem_rgb.eval()


print(
    "\nModel switched to evaluation mode."
)


# ============================================================
# Generate answer
# ============================================================

def generate_answer(
    q_text,
    img_id
):

    """
    Image pair
        ↓
    TerraFM
        ↓
    DeltaBlock
        ↓
    TCSSM
        ↓
    FusionProjector
        ↓
    TinyRS-R1 + trained LoRA
        ↓
    Generated answer
    """

    prompt = (
        "<|im_start|>user\n"
        + q_text
        + "<|im_end|>\n"
        + "<|im_start|>assistant\n"
    )

    with torch.no_grad():

        # ----------------------------------------------------
        # Load temporal image pair
        # ----------------------------------------------------

        im1, im2 = load_image_pair(
            img_id
        )

        # ----------------------------------------------------
        # IMPORTANT DTYPE FIX
        #
        # The RGB FlexiblePatchEmbed can be bfloat16 because
        # the model's modules are placed in the LLM dtype.
        #
        # torchvision produces float32 images.
        #
        # Therefore convert the images to the same dtype as
        # the RGB stem before passing them into TerraFM.
        # ----------------------------------------------------

        stem_dtype = (
            model.flexible_stem_rgb
            .proj
            .weight
            .dtype
        )

        im1 = im1.to(
            dtype=stem_dtype
        )

        im2 = im2.to(
            dtype=stem_dtype
        )

        # ----------------------------------------------------
        # TerraFM embeddings
        # ----------------------------------------------------

        emb_t1 = model.encode(
            im1,
            model.flexible_stem_rgb
        )

        emb_t2 = model.encode(
            im2,
            model.flexible_stem_rgb
        )

        # ----------------------------------------------------
        # Temporal difference
        # ----------------------------------------------------

        delta = model.delta_block(
            emb_t1,
            emb_t2
        )

        # ----------------------------------------------------
        # Text prompt
        # ----------------------------------------------------

        text_ids = model.tokenizer(
            prompt,
            return_tensors="pt"
        ).input_ids.to(device)

        text_embeds = (
            model.llm
            .get_input_embeddings()(
                text_ids
            )
        )

        # ----------------------------------------------------
        # Text-conditioned temporal fusion
        # ----------------------------------------------------

        text_pooled = text_embeds.mean(
            dim=1
        )

        fused = model.tcssm_layer(
            delta,
            text_pooled
        )

        # ----------------------------------------------------
        # Project visual features into LLM space
        # ----------------------------------------------------

        vision_tokens = model.projector(
            fused
        )

        # ----------------------------------------------------
        # Combine vision + text
        # ----------------------------------------------------

        combined = torch.cat(
            [
                vision_tokens,
                text_embeds
            ],
            dim=1
        )

        attention_mask = torch.ones(
            (
                1,
                combined.shape[1]
            ),

            dtype=torch.long,

            device=device
        )

        # ----------------------------------------------------
        # Generate answer
        # ----------------------------------------------------

        output_ids = model.llm.generate(
            inputs_embeds=combined,
            attention_mask=attention_mask,
            max_new_tokens=MAX_NEW_TOKENS,
            pad_token_id=(
                model.tokenizer.eos_token_id
            ),
            do_sample=False,
        )

        raw_text = model.tokenizer.decode(
            output_ids[0],
            skip_special_tokens=True
        )

    return raw_text


# ============================================================
# Evaluation loop
# ============================================================

print(
    "\n" + "=" * 60
)

print(
    "Starting evaluation"
)

print(
    "=" * 60
)


predictions = []

ground_truth = []

q_types = []


for i, (_, row) in enumerate(
    eval_sample.iterrows(),
    start=1
):

    question_data = row[
        "question"
    ]

    q_text = question_data.get(
        "question",
        ""
    )

    img_id = int(
        question_data.get(
            "img_id",
            0
        )
    )

    gt = row["a_text"]

    q_type = row["q_type"]

    try:

        raw_output = generate_answer(
            q_text,
            img_id
        )

        prediction = extract_answer_v2(
            raw_output,
            answer_vocab
        )

        predictions.append(
            prediction
        )

        ground_truth.append(
            gt
        )

        q_types.append(
            q_type
        )

        print(
            "\n" + "-" * 60
        )

        print(
            f"Sample "
            f"{i}/{len(eval_sample)}"
        )

        print(
            f"Image ID      : {img_id}"
        )

        print(
            f"Type          : {q_type}"
        )

        print(
            f"Question      : {q_text}"
        )

        print(
            f"Ground truth  : {gt}"
        )

        print(
            f"Raw output    : {raw_output}"
        )

        print(
            f"Prediction    : {prediction}"
        )

    except Exception as e:

        print(
            "\n" + "-" * 60
        )

        print(
            f"ERROR on sample {i}"
        )

        print(
            f"Image ID: {img_id}"
        )

        print(
            f"Question: {q_text}"
        )

        print(
            f"Error: {type(e).__name__}: {e}"
        )

        raise


# ============================================================
# Overall accuracy
# ============================================================

if len(predictions) == 0:

    raise RuntimeError(
        "No predictions were produced."
    )


correct = sum(
    p == g
    for p, g in zip(
        predictions,
        ground_truth
    )
)

overall_acc = (
    correct / len(predictions)
)


print(
    "\n" + "=" * 60
)

print(
    "Evaluation Results"
)

print(
    "=" * 60
)


print(
    f"Correct: "
    f"{correct}/{len(predictions)}"
)

print(
    f"Overall accuracy: "
    f"{overall_acc * 100:.2f}%"
)


# ============================================================
# Accuracy by question type
# ============================================================

results_df = pd.DataFrame({

    "prediction": predictions,

    "ground_truth": ground_truth,

    "q_type": q_types,

})

results_df["correct"] = (
    results_df["prediction"]
    == results_df["ground_truth"]
)


print(
    "\nAccuracy by question type:"
)


for q_type, group in results_df.groupby(
    "q_type"
):

    type_correct = group[
        "correct"
    ].sum()

    type_total = len(group)

    type_acc = (
        type_correct / type_total
    )

    print(
        f"{q_type:25s} "
        f"{type_correct}/{type_total} "
        f"({type_acc * 100:.2f}%)"
    )


print(
    "\n" + "=" * 60
)

print(
    "Evaluation completed successfully."
)

print(
    "=" * 60
)
