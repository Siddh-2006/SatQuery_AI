"""
Run this ONCE, in the same working directory as your trained model (where
src/, configs/config.yaml, and runs/exp1/best.pt already exist). It needs
internet access (to finish loading/merging things already in memory) and
produces a fully self-contained, offline-loadable bundle:

    offline_model/
      llm/                merged Qwen weights + tokenizer (HF format)
      terrafm.pth         TerraFM backbone weights
      terrafm.py          upstream TerraFM architecture code (unmodified)
      projector.pt        Q-Former projector weights
      model_config.yaml   architecture hyperparameters needed to reload

Copy that whole folder + serve.py anywhere (even fully offline) to run it.

Usage:
    python export_offline_model.py --checkpoint runs/exp1/best.pt --out offline_model
"""
import argparse
import shutil
from pathlib import Path

import torch
import yaml

from src.models.captioner import EOCaptioner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/config.yaml")
    parser.add_argument("--checkpoint", default="runs/exp1/best.pt")
    parser.add_argument("--out", default="offline_model")
    args = parser.parse_args()

    cfg = yaml.safe_load(open(args.config))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Building model and loading checkpoint...")
    model = EOCaptioner(cfg["model"])
    ckpt = torch.load(args.checkpoint, map_location="cpu")
    model.projector.load_state_dict(ckpt["projector"])
    model.llm.load_state_dict(ckpt["llm_lora"], strict=False)
    if "backbone_lora" in ckpt:
        model.backbone.load_state_dict(ckpt["backbone_lora"], strict=False)

    print("Merging LoRA into base LLM weights (this can take a minute)...")
    merged_llm = model.llm.merge_and_unload()
    llm_dir = out_dir / "llm"
    merged_llm.save_pretrained(llm_dir, safe_serialization=True)
    model.tokenizer.save_pretrained(llm_dir)
    print(f"  -> saved merged LLM + tokenizer to {llm_dir}")

    # Backbone: if it was frozen (the default), its weights are exactly the
    # pretrained TerraFM checkpoint already -- just copy that file. If LoRA
    # was applied to it too, merge the same way as the LLM above.
    terrafm_ckpt_src = Path(cfg["model"]["terrafm_ckpt"])
    if cfg["model"].get("freeze_backbone", True):
        shutil.copy(terrafm_ckpt_src, out_dir / "terrafm.pth")
        print(f"  -> copied frozen TerraFM weights from {terrafm_ckpt_src}")
    else:
        merged_backbone = model.backbone.merge_and_unload()
        torch.save(merged_backbone.state_dict(), out_dir / "terrafm.pth")
        print("  -> saved merged (LoRA-tuned) TerraFM weights")

    # terrafm.py itself -- needed to reconstruct the backbone class offline
    terrafm_repo = Path(cfg["model"]["terrafm_repo"])
    shutil.copy(terrafm_repo / "terrafm.py", out_dir / "terrafm.py")

    torch.save(model.projector.state_dict(), out_dir / "projector.pt")
    print("  -> saved projector weights")

    minimal_cfg = {
        "terrafm_variant": cfg["model"].get("terrafm_variant", "base"),
        "s2_product": cfg["model"].get("s2_product", "l2a"),
        "qformer_num_queries": cfg["model"].get("qformer_num_queries", 32),
        "qformer_depth": cfg["model"].get("qformer_depth", 2),
        "qformer_heads": cfg["model"].get("qformer_heads", 8),
        "max_answer_tokens": cfg["model"].get("max_answer_tokens", 256),
        "image_size": cfg["data"].get("image_size", 224),
        "use_s1": cfg["data"].get("use_s1", True),
    }
    with open(out_dir / "model_config.yaml", "w") as f:
        yaml.safe_dump(minimal_cfg, f)

    print(f"\nDone. Offline bundle ready at: {out_dir.resolve()}")
    print("Copy this whole folder + serve.py to wherever you want to run it offline.")


if __name__ == "__main__":
    main()
