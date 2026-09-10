import torch

from model import BiTemporalModel
from dataset import CDVQADataset


print("Loading dataset...")
dataset = CDVQADataset(
    "data/cdvqa_train_clean.parquet",
    "data/cdvqa_annotations/Train_images.json",
    "data/second_images/SECOND_train_set",
)

sample = dataset[0]

print("Image 1:", sample["im1"].shape)
print("Image 2:", sample["im2"].shape)

print("\nLoading model...")
model = BiTemporalModel(
    terrafm_weights="/home/user5/My_model/models/terrafm/TerraFM-B.pth",
    llm_dir="/home/user5/My_model/models/tinyrs_r1",
)

device = next(model.llm.parameters()).device
dtype = next(model.llm.parameters()).dtype

im1 = sample["im1"].unsqueeze(0).to(device=device, dtype=dtype)
im2 = sample["im2"].unsqueeze(0).to(device=device, dtype=dtype)

print("\nRunning visual pipeline...")

emb_t1 = model.encode(im1, model.flexible_stem_rgb)
print("emb_t1:", emb_t1.shape)

emb_t2 = model.encode(im2, model.flexible_stem_rgb)
print("emb_t2:", emb_t2.shape)

delta = model.delta_block(emb_t1, emb_t2)
print("delta:", delta.shape)

text_embedding = torch.zeros(
    1,
    model.llm_hidden,
    device=device,
    dtype=dtype,
)

fused = model.tcssm_layer(delta, text_embedding)
print("TCSSM output:", fused.shape)

vision_tokens = model.projector(fused)
print("vision tokens:", vision_tokens.shape)

print("\nFORWARD PASS SUCCESSFUL")
