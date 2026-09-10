import torch
import torch.nn as nn
import timm

from transformers import (
    AutoTokenizer,
    Qwen2VLForConditionalGeneration,
    BitsAndBytesConfig,
)

from peft import LoraConfig, get_peft_model


class FlexiblePatchEmbed(nn.Module):

    def __init__(
        self,
        in_channels=3,
        patch_size=16,
        embed_dim=768,
    ):
        super().__init__()

        self.proj = nn.Conv2d(
            in_channels,
            embed_dim,
            kernel_size=patch_size,
            stride=patch_size,
        )

    def forward(self, x):

        x = self.proj(x)

        x = x.flatten(2).transpose(1, 2)

        return x


class DeltaBlock(nn.Module):

    def __init__(
        self,
        embed_dim=768,
        num_heads=8,
    ):
        super().__init__()

        self.cross_attn = nn.MultiheadAttention(
            embed_dim=embed_dim,
            num_heads=num_heads,
            batch_first=True,
        )

        self.mix = nn.Sequential(
            nn.Linear(
                embed_dim * 2,
                embed_dim * 2,
            ),
            nn.GELU(),
            nn.Linear(
                embed_dim * 2,
                embed_dim,
            ),
        )

        self.norm = nn.LayerNorm(embed_dim)

    def forward(
        self,
        emb_t1,
        emb_t2,
    ):

        subtracted = emb_t2 - emb_t1

        attended, _ = self.cross_attn(
            emb_t2,
            emb_t1,
            emb_t1,
        )

        combined = torch.cat(
            [subtracted, attended],
            dim=-1,
        )

        return self.norm(
            self.mix(combined)
        )


class TCSSMLayer(nn.Module):

    def __init__(
        self,
        embed_dim=768,
        text_dim=768,
    ):
        super().__init__()

        self.param_predictor = nn.Sequential(
            nn.Linear(
                embed_dim + text_dim,
                embed_dim,
            ),
            nn.GELU(),
            nn.Linear(
                embed_dim,
                embed_dim,
            ),
        )

        self.input_proj = nn.Linear(
            embed_dim,
            embed_dim,
        )

        self.out_proj = nn.Linear(
            embed_dim,
            embed_dim,
        )

    def forward(
        self,
        delta_seq,
        text_embedding,
    ):

        batch, seq_len, dim = delta_seq.shape

        text_expanded = (
            text_embedding
            .unsqueeze(1)
            .expand(-1, seq_len, -1)
        )

        gate_input = torch.cat(
            [delta_seq, text_expanded],
            dim=-1,
        )

        gate = torch.sigmoid(
            self.param_predictor(gate_input)
        )

        state = torch.zeros(
            batch,
            dim,
            device=delta_seq.device,
            dtype=delta_seq.dtype,
        )

        outputs = []

        for t in range(seq_len):

            x_t = self.input_proj(
                delta_seq[:, t, :]
            )

            g_t = gate[:, t, :]

            state = (
                g_t * state
                + (1 - g_t) * x_t
            )

            outputs.append(
                self.out_proj(state)
            )

        return torch.stack(
            outputs,
            dim=1,
        )


class FusionProjector(nn.Module):

    def __init__(
        self,
        in_dim=768,
        out_dim=1536,
    ):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(
                in_dim,
                out_dim,
            ),
            nn.GELU(),
            nn.Linear(
                out_dim,
                out_dim,
            ),
        )

    def forward(self, x):

        return self.net(x)


class BiTemporalModel(nn.Module):

    def __init__(
        self,
        terrafm_weights,
        llm_dir,
    ):
        super().__init__()

        self.device = torch.device(
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

        # --------------------------------------------------
        # TerraFM
        # --------------------------------------------------

        print("Creating TerraFM ViT-B/16...")

        self.backbone = timm.create_model(
            "vit_base_patch16_224",
            pretrained=False,
            num_classes=0,
        )

        print("Loading TerraFM checkpoint...")

        terrafm_state = torch.load(
            terrafm_weights,
            map_location="cpu",
        )

        missing, unexpected = (
            self.backbone.load_state_dict(
                terrafm_state,
                strict=False,
            )
        )

        print(
            "TerraFM missing keys:",
            len(missing),
        )

        print(
            "TerraFM unexpected keys:",
            len(unexpected),
        )

        print(
            "TerraFM parameters:",
            sum(
                p.numel()
                for p in self.backbone.parameters()
            ),
        )

        # --------------------------------------------------
        # RGB patch embedding
        # --------------------------------------------------

        pretrained_patch_weight = (
            self.backbone.patch_embed.proj.weight.data.clone()
        )

        pretrained_patch_bias = (
            self.backbone.patch_embed.proj.bias.data.clone()
        )

        self.flexible_stem_rgb = FlexiblePatchEmbed(
            in_channels=3,
            embed_dim=768,
        )

        self.flexible_stem_rgb.proj.weight.data.copy_(
            pretrained_patch_weight
        )

        self.flexible_stem_rgb.proj.bias.data.copy_(
            pretrained_patch_bias
        )

        # Other stems are retained because they are part
        # of the BiTemporal v2 architecture.

        self.flexible_stem_ms = FlexiblePatchEmbed(
            in_channels=12,
            embed_dim=768,
        )

        self.flexible_stem_sar = FlexiblePatchEmbed(
            in_channels=2,
            embed_dim=768,
        )

        self.backbone.patch_embed = (
            self.flexible_stem_rgb
        )

        # Freeze TerraFM.

        for p in self.backbone.parameters():
            p.requires_grad = False

        self.backbone.eval()

        # --------------------------------------------------
        # TinyRS-R1
        # --------------------------------------------------

        print("Loading TinyRS-R1...")

        self.tokenizer = AutoTokenizer.from_pretrained(
            llm_dir,
            trust_remote_code=True,
        )

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
        )

        self.llm = (
            Qwen2VLForConditionalGeneration.from_pretrained(
                llm_dir,
                quantization_config=bnb_config,
                device_map="auto",
                trust_remote_code=True,
            )
        )

        # --------------------------------------------------
        # LoRA
        # --------------------------------------------------

        lora_config = LoraConfig(
            r=16,
            lora_alpha=32,
            target_modules=[
                "q_proj",
                "v_proj",
            ],
            lora_dropout=0.05,
            bias="none",
            task_type=None,
        )

        self.llm = get_peft_model(
            self.llm,
            lora_config,
        )

        self.llm.gradient_checkpointing_enable()

        # Required because training uses inputs_embeds.

        self.llm.enable_input_require_grads()

        self.device = next(
            self.llm.parameters()
        ).device

        self.llm_dtype = next(
            self.llm.parameters()
        ).dtype

        self.llm_hidden = getattr(
            self.llm.config,
            "text_config",
            self.llm.config,
        ).hidden_size

        print(
            "LLM hidden size:",
            self.llm_hidden,
        )

        print(
            "LLM device:",
            self.device,
        )

        print(
            "LLM dtype:",
            self.llm_dtype,
        )

        # --------------------------------------------------
        # BiTemporal modules
        # --------------------------------------------------

        self.delta_block = DeltaBlock(
            embed_dim=768,
        ).to(
            device=self.device,
            dtype=self.llm_dtype,
        )

        self.tcssm_layer = TCSSMLayer(
            embed_dim=768,
            text_dim=self.llm_hidden,
        ).to(
            device=self.device,
            dtype=self.llm_dtype,
        )

        self.projector = FusionProjector(
            in_dim=768,
            out_dim=self.llm_hidden,
        ).to(
            device=self.device,
            dtype=self.llm_dtype,
        )

        self.backbone = self.backbone.to(
            device=self.device,
            dtype=self.llm_dtype,
        )

        self.flexible_stem_rgb = (
            self.flexible_stem_rgb.to(
                device=self.device,
                dtype=self.llm_dtype,
            )
        )

        print(
            "BiTemporal modules initialized."
        )

    def encode(
        self,
        x,
        stem,
    ):

        # Dataset images are float32.
        # TerraFM is stored in the LLM dtype
        # (bfloat16 on the current H100 setup).
        # Convert the input to match TerraFM.

        x = x.to(
            device=self.device,
            dtype=self.llm_dtype,
        )

        original_patch_embed = (
            self.backbone.patch_embed
        )

        self.backbone.patch_embed = stem

        try:

            with torch.no_grad():

                out = self.backbone.forward_features(
                    x
                )

        finally:

            self.backbone.patch_embed = (
                original_patch_embed
            )

        return out

    def get_vision_tokens(
        self,
        im1,
        im2,
        prompt_embeds,
    ):

        emb_t1 = self.encode(
            im1,
            self.flexible_stem_rgb,
        )

        emb_t2 = self.encode(
            im2,
            self.flexible_stem_rgb,
        )

        delta = self.delta_block(
            emb_t1,
            emb_t2,
        )

        text_pooled = prompt_embeds.mean(
            dim=1
        )

        fused = self.tcssm_layer(
            delta,
            text_pooled,
        )

        vision_tokens = self.projector(
            fused
        )

        return vision_tokens
