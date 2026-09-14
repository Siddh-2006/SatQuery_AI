import os
import shutil
import random

import yaml
import torch
import bitsandbytes as bnb

from torch.utils.data import DataLoader, Subset
from torch.optim.lr_scheduler import CosineAnnealingLR

from dataset import CDVQADataset
from model import BiTemporalModel


# ============================================================
# Configuration
# ============================================================

with open("configs/config.yaml", "r") as f:
    config = yaml.safe_load(f)

print("Configuration loaded.")


# ============================================================
# Paths
# ============================================================

train_parquet = config["paths"]["train_parquet"]
annotations = config["paths"]["annotations"]
image_root = config["paths"]["image_root"]

terrafm_weights = config["paths"]["terrafm_weights"]
llm_dir = config["paths"]["llm_dir"]

checkpoint_dir = config["paths"]["checkpoint_dir"]
log_dir = config["paths"]["log_dir"]

os.makedirs(checkpoint_dir, exist_ok=True)
os.makedirs(log_dir, exist_ok=True)


# ============================================================
# Training configuration
# ============================================================

batch_size = config["training"]["batch_size"]
num_epochs = config["training"]["num_epochs"]

gradient_accumulation_steps = (
    config["training"]["gradient_accumulation_steps"]
)

learning_rate = config["training"]["learning_rate"]
weight_decay = config["training"]["weight_decay"]
adam_eps = config["training"]["adam_eps"]

min_learning_rate = config["training"]["min_learning_rate"]


# ============================================================
# Training controls
# ============================================================

# Save a checkpoint every N optimizer steps.
CHECKPOINT_EVERY = 2000

# Automatically resume from checkpoints/latest.pt.
AUTO_RESUME = True

# ------------------------------------------------------------
# TEST SETTING
# ------------------------------------------------------------
# IMPORTANT:
# This number means OPTIMIZER steps.
#
# With gradient_accumulation_steps = 4:
#
#     8 optimizer steps
#     = 32 micro-batches
#
# Set this to None only when we are ready for real training.
# ------------------------------------------------------------

MAX_TRAIN_STEPS = None


# ============================================================
# RNG helpers
# ============================================================

def get_rng_state():
    """
    Save Python, PyTorch CPU, and CUDA RNG states.
    """

    state = {
        "python": random.getstate(),
        "torch": torch.get_rng_state(),
    }

    if torch.cuda.is_available():
        state["cuda"] = torch.cuda.get_rng_state_all()

    return state


def restore_rng_state(state):
    """
    Restore previously saved RNG states.
    """

    if state is None:
        return

    if "python" in state:
        random.setstate(state["python"])

    if "torch" in state:
        torch.set_rng_state(state["torch"])

    if torch.cuda.is_available() and "cuda" in state:
        torch.cuda.set_rng_state_all(state["cuda"])


# ============================================================
# Checkpoint helper
# ============================================================

def save_checkpoint(
    model,
    optimizer,
    scheduler,
    epoch,
    next_batch_in_epoch,
    micro_batch_step,
    optimizer_step,
    epoch_indices,
    checkpoint_path,
    lora_checkpoint_dir,
):
    """
    Save the complete trainable state.

    Saved information:

      - BiTemporal trainable modules
      - LoRA adapter
      - optimizer
      - scheduler
      - RNG state
      - current epoch
      - next micro-batch to process
      - micro-batch counter
      - optimizer-step counter
      - exact sampled order for the current epoch
    """

    # --------------------------------------------------------
    # Save LoRA first.
    # --------------------------------------------------------

    temp_lora_dir = lora_checkpoint_dir + ".tmp"

    if os.path.exists(temp_lora_dir):
        shutil.rmtree(temp_lora_dir)

    os.makedirs(temp_lora_dir, exist_ok=True)

    model.llm.save_pretrained(temp_lora_dir)

    # Replace previous LoRA directory.
    if os.path.exists(lora_checkpoint_dir):
        shutil.rmtree(lora_checkpoint_dir)

    os.replace(
        temp_lora_dir,
        lora_checkpoint_dir,
    )

    # --------------------------------------------------------
    # Main checkpoint.
    # --------------------------------------------------------

    checkpoint = {
        "epoch": epoch,
        "next_batch_in_epoch": next_batch_in_epoch,

        "micro_batch_step": micro_batch_step,
        "global_step": micro_batch_step,

        "optimizer_step": optimizer_step,

        "epoch_indices": epoch_indices,

        "model_state": {
            "projector":
                model.projector.state_dict(),

            "delta_block":
                model.delta_block.state_dict(),

            "tcssm_layer":
                model.tcssm_layer.state_dict(),

            "vision_stem":
                model.flexible_stem_rgb.state_dict(),
        },

        "optimizer_state":
            optimizer.state_dict(),

        "scheduler_state":
            scheduler.state_dict(),

        "rng_state":
            get_rng_state(),

        "lora_checkpoint_dir":
            lora_checkpoint_dir,
    }

    temp_checkpoint_path = checkpoint_path + ".tmp"

    torch.save(
        checkpoint,
        temp_checkpoint_path,
    )

    os.replace(
        temp_checkpoint_path,
        checkpoint_path,
    )

    # --------------------------------------------------------
    # Update latest.pt atomically.
    # --------------------------------------------------------

    latest_path = os.path.join(
        checkpoint_dir,
        "latest.pt",
    )

    temp_latest_path = latest_path + ".tmp"

    shutil.copy2(
        checkpoint_path,
        temp_latest_path,
    )

    os.replace(
        temp_latest_path,
        latest_path,
    )

    print()
    print("--------------------------------------------------")
    print("CHECKPOINT SAVED")
    print("Checkpoint:", checkpoint_path)
    print("LoRA:", lora_checkpoint_dir)
    print("Latest:", latest_path)
    print("Epoch:", epoch)
    print("Next batch:", next_batch_in_epoch)
    print("Micro-batches:", micro_batch_step)
    print("Optimizer steps:", optimizer_step)
    print("--------------------------------------------------")
    print()


# ============================================================
# Dataset
# ============================================================

print("Loading training dataset...")

train_dataset = CDVQADataset(
    train_parquet,
    annotations,
    image_root,
)

print(
    "Training samples:",
    len(train_dataset),
)


# ============================================================
# Weighted sampling
# ============================================================

q_types = train_dataset.df["question"].apply(
    lambda x: x["type"]
)

class_counts = q_types.value_counts()

sample_weights = q_types.apply(
    lambda q: 1.0 / class_counts[q]
).tolist()

sample_weights = torch.DoubleTensor(
    sample_weights
)

print(
    "Question types:",
    len(class_counts),
)

print("Weighted sampler: enabled")


# ============================================================
# GPU
# ============================================================

print(
    "CUDA available:",
    torch.cuda.is_available(),
)

if not torch.cuda.is_available():
    raise RuntimeError(
        "CUDA GPU is required for training."
    )

print(
    "GPU:",
    torch.cuda.get_device_name(0),
)


# ============================================================
# Model
# ============================================================

print("\nLoading BiTemporal model...")

model = BiTemporalModel(
    terrafm_weights=terrafm_weights,
    llm_dir=llm_dir,
)

print("Model loaded.")


# ============================================================
# Training mode
# ============================================================

model.llm.train()
model.projector.train()
model.delta_block.train()
model.tcssm_layer.train()


# ============================================================
# Optimizer
# ============================================================

trainable_params = (
    list(model.llm.parameters())
    + list(model.projector.parameters())
    + list(model.delta_block.parameters())
    + list(model.tcssm_layer.parameters())
)

optimizer = bnb.optim.AdamW8bit(
    trainable_params,
    lr=learning_rate,
    eps=adam_eps,
    weight_decay=weight_decay,
)

print("Optimizer created.")
print("Learning rate:", learning_rate)

print(
    "Trainable parameter tensors:",
    len(trainable_params),
)


# ============================================================
# Number of optimizer steps
# ============================================================

micro_batches_per_epoch = (
    len(train_dataset)
    // batch_size
)

optimizer_steps_per_epoch = (
    micro_batches_per_epoch
    // gradient_accumulation_steps
)

total_optimizer_steps = (
    optimizer_steps_per_epoch
    * num_epochs
)

scheduler = CosineAnnealingLR(
    optimizer,
    T_max=total_optimizer_steps,
    eta_min=min_learning_rate,
)

print(
    "Micro-batches per epoch:",
    micro_batches_per_epoch,
)

print(
    "Optimizer steps per epoch:",
    optimizer_steps_per_epoch,
)

print(
    "Total optimizer steps:",
    total_optimizer_steps,
)

print("Scheduler: cosine")


# ============================================================
# Resume state
# ============================================================

latest_checkpoint = os.path.join(
    checkpoint_dir,
    "latest.pt",
)

start_epoch = 0
next_batch_in_epoch = 0

micro_batch_step = 0
optimizer_step = 0

resume_epoch_indices = None
resume_lora_dir = None


# ============================================================
# Resume from latest checkpoint
# ============================================================

if AUTO_RESUME and os.path.exists(
    latest_checkpoint
):

    print()
    print("========================================")
    print("LATEST CHECKPOINT FOUND")
    print("========================================")

    print(
        "Loading:",
        latest_checkpoint,
    )

    checkpoint = torch.load(
        latest_checkpoint,
        map_location="cpu",
    )

    # --------------------------------------------------------
    # Restore BiTemporal modules
    # --------------------------------------------------------

    model.projector.load_state_dict(
        checkpoint["model_state"]["projector"]
    )

    model.delta_block.load_state_dict(
        checkpoint["model_state"]["delta_block"]
    )

    model.tcssm_layer.load_state_dict(
        checkpoint["model_state"]["tcssm_layer"]
    )

    model.flexible_stem_rgb.load_state_dict(
        checkpoint["model_state"]["vision_stem"]
    )

    # --------------------------------------------------------
    # Restore optimizer
    # --------------------------------------------------------

    optimizer.load_state_dict(
        checkpoint["optimizer_state"]
    )

    # --------------------------------------------------------
    # Restore scheduler
    # --------------------------------------------------------

    scheduler.load_state_dict(
        checkpoint["scheduler_state"]
    )

    # --------------------------------------------------------
    # Restore counters
    # --------------------------------------------------------

    saved_epoch = checkpoint["epoch"]

    saved_next_batch = checkpoint.get(
        "next_batch_in_epoch",
        0,
    )

    saved_micro_batch_step = checkpoint.get(
        "micro_batch_step",
        checkpoint.get("global_step", 0),
    )

    saved_optimizer_step = checkpoint[
        "optimizer_step"
    ]

    # --------------------------------------------------------
    # Check whether checkpoint is at the end of epoch.
    # --------------------------------------------------------

    if saved_next_batch >= micro_batches_per_epoch:

        start_epoch = saved_epoch
        next_batch_in_epoch = 0
        resume_epoch_indices = None

    else:

        start_epoch = saved_epoch - 1
        next_batch_in_epoch = saved_next_batch

        resume_epoch_indices = checkpoint.get(
            "epoch_indices"
        )

    micro_batch_step = saved_micro_batch_step
    optimizer_step = saved_optimizer_step

    # --------------------------------------------------------
    # LoRA
    # --------------------------------------------------------

    resume_lora_dir = checkpoint.get(
        "lora_checkpoint_dir",
        None,
    )

    print(
        "Checkpoint epoch:",
        saved_epoch,
    )

    print(
        "Checkpoint next batch:",
        saved_next_batch,
    )

    print(
        "Checkpoint micro-batches:",
        saved_micro_batch_step,
    )

    print(
        "Checkpoint optimizer steps:",
        saved_optimizer_step,
    )

    print(
        "LoRA directory:",
        resume_lora_dir,
    )

    # --------------------------------------------------------
    # Restore LoRA
    # --------------------------------------------------------

    if resume_lora_dir is not None:

        if not os.path.isabs(resume_lora_dir):
            resume_lora_dir = os.path.normpath(
                resume_lora_dir
            )

        if os.path.exists(resume_lora_dir):

            print(
                "Loading LoRA adapter..."
            )

            model.llm.load_adapter(
                resume_lora_dir,
                adapter_name="default",
            )

            print(
                "LoRA adapter restored."
            )

        else:

            print(
                "WARNING: LoRA checkpoint directory "
                "does not exist:"
            )

            print(resume_lora_dir)

            print(
                "Continuing with current LoRA weights."
            )

    # --------------------------------------------------------
    # Restore RNG
    # --------------------------------------------------------

    restore_rng_state(
        checkpoint.get("rng_state")
    )

    print()
    print("Checkpoint restoration completed.")
    print()

else:

    print()
    print(
        "No previous checkpoint found."
    )

    print(
        "Starting training from scratch."
    )

    print()


# ============================================================
# Training loop
# ============================================================

print()
print("========================================")
print("STARTING TRAINING")
print("========================================")

print(
    "Starting epoch:",
    start_epoch + 1,
)

print(
    "Starting micro-batch:",
    next_batch_in_epoch,
)

print(
    "Starting optimizer step:",
    optimizer_step,
)

print(
    "Checkpoint frequency:",
    CHECKPOINT_EVERY,
    "optimizer steps",
)

if MAX_TRAIN_STEPS is not None:

    print(
        "TEST LIMIT:",
        MAX_TRAIN_STEPS,
        "optimizer steps",
    )

print()


# ============================================================
# Training
# ============================================================

optimizer.zero_grad()

training_finished = False


for epoch in range(
    start_epoch,
    num_epochs,
):

    print()
    print(
        "========== EPOCH "
        f"{epoch + 1}/{num_epochs} =========="
    )

    epoch_loss = 0.0
    epoch_micro_batches = 0

    # --------------------------------------------------------
    # Create exact sample order for this epoch.
    # --------------------------------------------------------

    if (
        epoch == start_epoch
        and resume_epoch_indices is not None
    ):

        epoch_indices = resume_epoch_indices

        print(
            "Using saved sampling order."
        )

    else:

        generator = torch.Generator()

        generator.manual_seed(
            12345 + epoch
        )

        epoch_indices = torch.multinomial(
            sample_weights,
            num_samples=len(train_dataset),
            replacement=True,
            generator=generator,
        ).tolist()

        print(
            "Generated new sampling order."
        )

    # --------------------------------------------------------
    # DataLoader for this exact epoch.
    # --------------------------------------------------------

    epoch_dataset = Subset(
        train_dataset,
        epoch_indices,
    )

    train_loader = DataLoader(
        epoch_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
	drop_last=True
    )

    print(
        "Resume batch within epoch:",
        next_batch_in_epoch
        if epoch == start_epoch
        else 0,
    )

    current_start_batch = (
        next_batch_in_epoch
        if epoch == start_epoch
        else 0
    )

    # --------------------------------------------------------
    # Iterate through epoch.
    # --------------------------------------------------------

    for step, batch in enumerate(
        train_loader
    ):

        # ----------------------------------------------------
        # Skip already completed batches.
        # ----------------------------------------------------

        if step < current_start_batch:
            continue

        # ----------------------------------------------------
        # Safety limit.
        #
        # IMPORTANT:
        # This checks optimizer_step, NOT micro-batches.
        # ----------------------------------------------------

        if (
            MAX_TRAIN_STEPS is not None
            and optimizer_step >= MAX_TRAIN_STEPS
        ):

            training_finished = True
            break

        # ----------------------------------------------------
        # Device and dtype
        # ----------------------------------------------------

        device = next(
            model.llm.parameters()
        ).device

        dtype = next(
            model.llm.parameters()
        ).dtype

        # ----------------------------------------------------
        # Images
        # ----------------------------------------------------

        im1 = batch["im1"].to(
            device=device,
            dtype=dtype,
        )

        im2 = batch["im2"].to(
            device=device,
            dtype=dtype,
        )

        # ----------------------------------------------------
        # Visual pipeline
        # ----------------------------------------------------

        emb_t1 = model.encode(
            im1,
            model.flexible_stem_rgb,
        )

        emb_t2 = model.encode(
            im2,
            model.flexible_stem_rgb,
        )

        delta = model.delta_block(
            emb_t1,
            emb_t2,
        )

        # ----------------------------------------------------
        # Text inputs
        # ----------------------------------------------------

        prompts = [
            "<|im_start|>user\n"
            + q
            + "<|im_end|>\n"
            "<|im_start|>assistant\n"
            for q in batch["q_text"]
        ]

        targets = [
            a + "<|im_end|>\n"
            for a in batch["a_text"]
        ]

        prompt_enc = model.tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
        ).to(device)

        target_enc = model.tokenizer(
            targets,
            return_tensors="pt",
            padding=True,
        ).to(device)

        # ----------------------------------------------------
        # Token embeddings
        # ----------------------------------------------------

        prompt_embeds = (
            model.llm.get_input_embeddings()(
                prompt_enc.input_ids
            )
        )

        target_embeds = (
            model.llm.get_input_embeddings()(
                target_enc.input_ids
            )
        )

        # ----------------------------------------------------
        # TCSSM
        # ----------------------------------------------------

        text_pooled = prompt_embeds.mean(
            dim=1
        )

        fused = model.tcssm_layer(
            delta,
            text_pooled,
        )

        # ----------------------------------------------------
        # Fusion projector
        # ----------------------------------------------------

        vision_tokens = model.projector(
            fused
        )

        # ----------------------------------------------------
        # Combine vision + prompt + target
        # ----------------------------------------------------

        inputs_embeds = torch.cat(
            [
                vision_tokens,
                prompt_embeds,
                target_embeds,
            ],
            dim=1,
        )

        # ----------------------------------------------------
        # Labels
        # ----------------------------------------------------

        labels = torch.full(
            inputs_embeds.shape[:2],
            -100,
            dtype=torch.long,
            device=device,
        )

        labels[
            :,
            vision_tokens.shape[1]
            + prompt_embeds.shape[1]:
        ] = target_enc.input_ids

        # ----------------------------------------------------
        # Forward
        # ----------------------------------------------------

        outputs = model.llm(
            inputs_embeds=inputs_embeds,
            labels=labels,
        )

        loss = outputs.loss

        loss_value = loss.item()

        epoch_loss += loss_value
        epoch_micro_batches += 1

        # ----------------------------------------------------
        # Gradient accumulation
        # ----------------------------------------------------

        scaled_loss = (
            loss
            / gradient_accumulation_steps
        )

        scaled_loss.backward()

        # ----------------------------------------------------
        # Count completed micro-batch.
        # ----------------------------------------------------

        micro_batch_step += 1

        next_batch = step + 1

        # ----------------------------------------------------
        # Optimizer update
        # ----------------------------------------------------

        should_update = (
            next_batch
            % gradient_accumulation_steps
            == 0
        )

        if should_update:

            optimizer.step()

            scheduler.step()

            optimizer.zero_grad()

            optimizer_step += 1

            current_lr = (
                scheduler.get_last_lr()[0]
            )

            print(
                f"Epoch {epoch + 1} | "
                f"Batch {next_batch} | "
                f"Optimizer step "
                f"{optimizer_step} | "
                f"Loss {loss_value:.4f} | "
                f"LR {current_lr:.8f}"
            )

            # ------------------------------------------------
            # Periodic checkpoint
            # ------------------------------------------------

            if (
                optimizer_step
                % CHECKPOINT_EVERY
                == 0
            ):

                step_checkpoint_path = os.path.join(
                    checkpoint_dir,
                    (
                        "checkpoint_step_"
                        f"{optimizer_step:06d}.pt"
                    ),
                )

                step_lora_dir = os.path.join(
                    checkpoint_dir,
                    (
                        "tinyrs_r1_lora_step_"
                        f"{optimizer_step:06d}"
                    ),
                )

                save_checkpoint(
                    model=model,
                    optimizer=optimizer,
                    scheduler=scheduler,
                    epoch=epoch + 1,
                    next_batch_in_epoch=next_batch,
                    micro_batch_step=micro_batch_step,
                    optimizer_step=optimizer_step,
                    epoch_indices=epoch_indices,
                    checkpoint_path=step_checkpoint_path,
                    lora_checkpoint_dir=step_lora_dir,
                )

        # ----------------------------------------------------
        # Check optimizer-step safety limit.
        # ----------------------------------------------------

        if (
            MAX_TRAIN_STEPS is not None
            and optimizer_step >= MAX_TRAIN_STEPS
        ):

            training_finished = True
            break

    # --------------------------------------------------------
    # If safety limit was reached, save immediately.
    # --------------------------------------------------------

    if training_finished:

        print()
        print(
            "Safety limit reached at optimizer step:",
            optimizer_step,
        )

        safety_checkpoint_path = os.path.join(
            checkpoint_dir,
            "checkpoint_test.pt",
        )

        safety_lora_dir = os.path.join(
            checkpoint_dir,
            "tinyrs_r1_lora_test",
        )

        save_checkpoint(
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            epoch=epoch + 1,
            next_batch_in_epoch=(
                next_batch
                if "next_batch" in locals()
                else current_start_batch
            ),
            micro_batch_step=micro_batch_step,
            optimizer_step=optimizer_step,
            epoch_indices=epoch_indices,
            checkpoint_path=safety_checkpoint_path,
            lora_checkpoint_dir=safety_lora_dir,
        )

        print()
        print(
            "========================================"
        )
        print(
            "SAFETY-LIMITED TRAINING COMPLETED"
        )
        print(
            "========================================"
        )

        break

    # --------------------------------------------------------
    # Epoch summary
    # --------------------------------------------------------

    average_loss = (
        epoch_loss
        / max(epoch_micro_batches, 1)
    )

    print()
    print(
        f"Epoch {epoch + 1} completed."
    )

    print(
        f"Average loss: {average_loss:.4f}"
    )

    print(
        "Micro-batches this epoch:",
        epoch_micro_batches,
    )

    print(
        "Total micro-batches:",
        micro_batch_step,
    )

    print(
        "Total optimizer steps:",
        optimizer_step,
    )

    # --------------------------------------------------------
    # Epoch checkpoint.
    # --------------------------------------------------------

    epoch_checkpoint_path = os.path.join(
        checkpoint_dir,
        (
            "checkpoint_epoch_"
            f"{epoch + 1}.pt"
        ),
    )

    epoch_lora_dir = os.path.join(
        checkpoint_dir,
        (
            "tinyrs_r1_lora_epoch_"
            f"{epoch + 1}"
        ),
    )

    save_checkpoint(
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        epoch=epoch + 1,
        next_batch_in_epoch=len(train_loader),
        micro_batch_step=micro_batch_step,
        optimizer_step=optimizer_step,
        epoch_indices=epoch_indices,
        checkpoint_path=epoch_checkpoint_path,
        lora_checkpoint_dir=epoch_lora_dir,
    )

    print(
        "Epoch checkpoint saved."
    )

    # --------------------------------------------------------
    # Next epoch starts from batch zero.
    # --------------------------------------------------------

    next_batch_in_epoch = 0
    resume_epoch_indices = None


# ============================================================
# Final message
# ============================================================

print()
print("========================================")
print("TRAINING SCRIPT FINISHED")
print("========================================")

print(
    "Total micro-batches processed:",
    micro_batch_step,
)

print(
    "Total optimizer steps:",
    optimizer_step,
)

print(
    "Checkpoints stored in:",
    checkpoint_dir,
)

print(
    "Latest checkpoint:",
    latest_checkpoint,
)
