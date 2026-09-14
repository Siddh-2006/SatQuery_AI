import torch

from model import BiTemporalModel
from dataset import CDVQADataset


dataset = CDVQADataset(
    "data/cdvqa_train_clean.parquet",
    "data/cdvqa_annotations/Train_images.json",
    "data/second_images/SECOND_train_set",
)

sample = dataset[0]

print("Loading model...")

model = BiTemporalModel(
    terrafm_weights="/home/user5/My_model/models/terrafm/TerraFM-B.pth",
    llm_dir="/home/user5/My_model/models/tinyrs_r1",
)

device = next(model.llm.parameters()).device
dtype = next(model.llm.parameters()).dtype

im1 = sample["im1"].unsqueeze(0).to(device=device, dtype=dtype)
im2 = sample["im2"].unsqueeze(0).to(device=device, dtype=dtype)

print("Running vision...")

emb_t1 = model.encode(im1, model.flexible_stem_rgb)
emb_t2 = model.encode(im2, model.flexible_stem_rgb)

delta = model.delta_block(emb_t1, emb_t2)

prompt = sample["q_text"]

prompt_text = (
    "<|im_start|>user\n"
    + prompt +
    "<|im_end|>\n"
    "<|im_start|>assistant\n"
)

target_text = sample["a_text"] + "<|im_end|>\n"

prompt_enc = model.tokenizer(
    [prompt_text],
    return_tensors="pt",
    padding=True,
).to(device)

target_enc = model.tokenizer(
    [target_text],
    return_tensors="pt",
    padding=True,
).to(device)

prompt_embeds = model.llm.get_input_embeddings()(
    prompt_enc.input_ids
)

target_embeds = model.llm.get_input_embeddings()(
    target_enc.input_ids
)

text_pooled = prompt_embeds.mean(dim=1)

fused = model.tcssm_layer(delta, text_pooled)

vision_tokens = model.projector(fused)

inputs_embeds = torch.cat(
    [vision_tokens, prompt_embeds, target_embeds],
    dim=1,
)

labels = torch.full(
    (1, inputs_embeds.shape[1]),
    -100,
    dtype=torch.long,
    device=device,
)

labels[
    :,
    vision_tokens.shape[1] + prompt_embeds.shape[1]:
] = target_enc.input_ids

print("Running LLM forward...")

outputs = model.llm(
    inputs_embeds=inputs_embeds,
    labels=labels,
)

loss = outputs.loss

print("Loss:", loss.item())

print("Running backward...")

loss.backward()

print("Backward completed.")

print("\nGradient check:")

for name, module in [
    ("DeltaBlock", model.delta_block),
    ("TCSSM", model.tcssm_layer),
    ("Projector", model.projector),
]:
    grads = [
        p.grad
        for p in module.parameters()
        if p.requires_grad and p.grad is not None
    ]

    if grads:
        total = sum(g.abs().sum().item() for g in grads)
        print(name, "gradient sum:", total)
    else:
        print(name, "NO GRADIENT")


lora_grads = []

for name, p in model.llm.named_parameters():
    if p.requires_grad and "lora_" in name and p.grad is not None:
        lora_grads.append(p.grad.abs().sum().item())

print("LoRA gradient tensors:", len(lora_grads))

if lora_grads:
    print("LoRA gradient sum:", sum(lora_grads))

print("\nTerraFM gradient check:")

terra_grads = [
    p.grad
    for p in model.backbone.parameters()
    if p.grad is not None
]

print("TerraFM parameters with gradients:", len(terra_grads))

print("\nBACKWARD TEST COMPLETE")
