import torch
import bitsandbytes as bnb

from model import BiTemporalModel
from dataset import CDVQADataset


dataset = CDVQADataset(
    "data/cdvqa_train_clean.parquet",
    "data/cdvqa_annotations/Train_images.json",
    "data/second_images/SECOND_train_set",
)

sample = dataset[0]

model = BiTemporalModel(
    terrafm_weights="/home/user5/My_model/models/terrafm/TerraFM-B.pth",
    llm_dir="/home/user5/My_model/models/tinyrs_r1",
)

device = next(model.llm.parameters()).device
dtype = next(model.llm.parameters()).dtype

im1 = sample["im1"].unsqueeze(0).to(device=device, dtype=dtype)
im2 = sample["im2"].unsqueeze(0).to(device=device, dtype=dtype)

emb_t1 = model.encode(im1, model.flexible_stem_rgb)
emb_t2 = model.encode(im2, model.flexible_stem_rgb)
delta = model.delta_block(emb_t1, emb_t2)

prompt_text = (
    "<|im_start|>user\n"
    + sample["q_text"]
    + "<|im_end|>\n"
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

prompt_embeds = model.llm.get_input_embeddings()(prompt_enc.input_ids)
target_embeds = model.llm.get_input_embeddings()(target_enc.input_ids)

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

outputs = model.llm(
    inputs_embeds=inputs_embeds,
    labels=labels,
)

loss = outputs.loss

print("Loss before update:", loss.item())

optimizer = bnb.optim.AdamW8bit(
    list(model.llm.parameters())
    + list(model.projector.parameters())
    + list(model.delta_block.parameters())
    + list(model.tcssm_layer.parameters()),
    lr=3e-5,
    eps=1e-4,
    weight_decay=0.01,
)

before = model.projector.net[0].weight.detach().clone()

optimizer.zero_grad()
loss.backward()
optimizer.step()

after = model.projector.net[0].weight.detach()

difference = (after - before).abs().sum().item()

print("Projector weight change:", difference)

if difference > 0:
    print("OPTIMIZER UPDATE SUCCESSFUL")
else:
    print("ERROR: Projector weights did not change")
