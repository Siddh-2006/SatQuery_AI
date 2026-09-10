import os
import argparse
import yaml
import torch

from PIL import Image
from torchvision import transforms

from model import BiTemporalModel


# ============================================================
# Configuration
# ============================================================

CONFIG_PATH = "configs/config.yaml"

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)


TERAFM_WEIGHTS = config["paths"]["terrafm_weights"]
LLM_DIR = config["paths"]["llm_dir"]

CHECKPOINT_DIR = config["paths"]["checkpoint_dir"]

BITEMPORAL_CHECKPOINT = os.path.join(
    CHECKPOINT_DIR,
    "bitemporal_v2.pt"
)

LORA_CHECKPOINT = os.path.join(
    CHECKPOINT_DIR,
    "tinyrs_r1_lora_epoch_3"
)

MAX_NEW_TOKENS = config["evaluation"]["max_new_tokens"]


# ============================================================
# Device
# ============================================================

device = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)

print("=" * 60)
print("BiTemporal v2 Inference")
print("=" * 60)

print(f"Device: {device}")

if torch.cuda.is_available():
    print(
        f"GPU: {torch.cuda.get_device_name(0)}"
    )


# ============================================================
# Image transform
# ============================================================

transform = transforms.Compose([
    transforms.Resize((224, 224)),
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
# Load image
# ============================================================

def load_image(path):

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Image not found: {path}"
        )

    image = Image.open(path).convert("RGB")

    image = transform(image).unsqueeze(0)

    return image.to(device)


# ============================================================
# Load model
# ============================================================

print("\nLoading BiTemporal model...")

model = BiTemporalModel(
    terrafm_weights=TERAFM_WEIGHTS,
    llm_dir=LLM_DIR,
)


# ============================================================
# Load trained BiTemporal weights
# ============================================================

print("\nLoading trained BiTemporal weights...")

if not os.path.exists(BITEMPORAL_CHECKPOINT):
    raise FileNotFoundError(
        f"BiTemporal checkpoint not found:\n"
        f"{BITEMPORAL_CHECKPOINT}"
    )


state = torch.load(
    BITEMPORAL_CHECKPOINT,
    map_location="cpu",
    weights_only=True
)


model.projector.load_state_dict(
    state["projector"]
)

model.delta_block.load_state_dict(
    state["delta_block"]
)

model.tcssm_layer.load_state_dict(
    state["tcssm_layer"]
)

model.flexible_stem_rgb.load_state_dict(
    state["vision_stem"]
)

print("Projector loaded.")
print("DeltaBlock loaded.")
print("TCSSM loaded.")
print("RGB vision stem loaded.")


# ============================================================
# Load trained LoRA adapter
# ============================================================

print("\nLoading trained LoRA adapter...")

if not os.path.isdir(LORA_CHECKPOINT):
    raise FileNotFoundError(
        f"LoRA checkpoint directory not found:\n"
        f"{LORA_CHECKPOINT}"
    )


model.llm.load_adapter(
    LORA_CHECKPOINT,
    adapter_name="default"
)

print("LoRA adapter loaded successfully.")


# ============================================================
# Evaluation mode
# ============================================================

model.eval()
model.llm.eval()
model.projector.eval()
model.delta_block.eval()
model.tcssm_layer.eval()
model.flexible_stem_rgb.eval()

print("\nModel ready for inference.")


# ============================================================
# Generate answer
# ============================================================

def generate_answer(
    image1_path,
    image2_path,
    question
):

    prompt = (
        "<|im_start|>user\n"
        + question
        + "<|im_end|>\n"
        + "<|im_start|>assistant\n"
    )

    with torch.no_grad():

        # ----------------------------------------------------
        # Load images
        # ----------------------------------------------------

        im1 = load_image(image1_path)
        im2 = load_image(image2_path)

        # ----------------------------------------------------
        # Match TerraFM stem dtype
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
        # Text embeddings
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
        # Project into LLM space
        # ----------------------------------------------------

        vision_tokens = model.projector(
            fused
        )

        # ----------------------------------------------------
        # Combine vision + question
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

        return raw_text.strip()


# ============================================================
# Command-line interface
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="BiTemporal v2 inference"
    )

    parser.add_argument(
        "--image1",
        required=True,
        help="Path to first temporal image"
    )

    parser.add_argument(
        "--image2",
        required=True,
        help="Path to second temporal image"
    )

    parser.add_argument(
        "--question",
        required=True,
        help="Question about the temporal image pair"
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("Running inference")
    print("=" * 60)

    print(f"Image 1: {args.image1}")
    print(f"Image 2: {args.image2}")
    print(f"Question: {args.question}")

    answer = generate_answer(
        args.image1,
        args.image2,
        args.question
    )

    print("\n" + "=" * 60)
    print("ANSWER")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
