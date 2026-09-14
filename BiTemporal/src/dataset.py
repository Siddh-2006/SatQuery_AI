import os
import json
import pandas as pd
from PIL import Image

import torch
from torch.utils.data import Dataset
from torchvision import transforms


class CDVQADataset(Dataset):

    def __init__(self, parquet_path, annotations_path, image_root):

        self.df = pd.read_parquet(parquet_path)

        with open(annotations_path, "r") as f:
            annotations = json.load(f)

        # Map image ID -> actual filename
        self.image_map = {
            int(img["id"]): img["file_name"]
            for img in annotations["images"]
        }

        self.image_root = image_root

        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            ),
        ])

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):

        row = self.df.iloc[idx]

        question = row["question"]
        answer = row["answer"]

        img_id = int(question["img_id"])

        q_text = str(question["question"])
        q_type = str(question["type"])
        a_text = str(answer["answer"])

        if img_id not in self.image_map:
            raise KeyError(
                f"Image ID {img_id} not found in Train_images.json"
            )

        filename = self.image_map[img_id]

        im1_path = os.path.join(
            self.image_root, "im1", filename
        )

        im2_path = os.path.join(
            self.image_root, "im2", filename
        )

        if not os.path.exists(im1_path):
            raise FileNotFoundError(im1_path)

        if not os.path.exists(im2_path):
            raise FileNotFoundError(im2_path)

        im1 = Image.open(im1_path).convert("RGB")
        im2 = Image.open(im2_path).convert("RGB")

        im1 = self.transform(im1)
        im2 = self.transform(im2)

        return {
            "im1": im1,
            "im2": im2,
            "q_text": q_text,
            "a_text": a_text,
            "img_id": img_id,
            "q_type": q_type,
        }
