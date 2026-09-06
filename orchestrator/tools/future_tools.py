"""
tools/future_tools.py
=======================
Tool *definitions* for the specialist models that aren't built yet
(change detection, cross-modal fusion, segmentation) -- see
`orchestrator/DESIGN.md` §4 and the corresponding
`system_prompts/<name>/` folders for what each will eventually do.

IMPORTANT: nothing in here is imported by `registry.py` while its matching
`system_prompts/<name>/capabilities.json` says `"status": "not_ready"`.
These functions exist purely as a drafting space / reminder of the
intended shape, so wiring up a real backend later is "fill in the body
and flip the registry," not "design the tool from scratch." Do not call
these directly -- they raise `NotImplementedError` on purpose.
"""
from langchain_core.tools import tool


@tool
def query_change_detection(patch_id_t1: str, patch_id_t2: str, instruction: str) -> str:
    """PLANNED, not yet callable. Will describe/answer questions about what
    changed between two captures of the same location (a bi-temporal
    pair) using a ChangeChat/DeltaVLM-style model. See
    system_prompts/change_detection_changechat/SYSTEM_PROMPT.md."""
    raise NotImplementedError("change-detection model is not integrated yet -- see system_prompts/change_detection_changechat/")


@tool
def query_cross_modal_fusion(optical_patch_id: str, sar_patch_id: str, instruction: str) -> str:
    """PLANNED, not yet callable. Will jointly reason over a co-registered
    optical+SAR pair using TerraFM's gated cross-attention fusion. See
    system_prompts/cross_modal_fusion_terrafm/SYSTEM_PROMPT.md."""
    raise NotImplementedError("cross-modal fusion model is not integrated yet -- see system_prompts/cross_modal_fusion_terrafm/")


@tool
def query_segmentation(patch_id: str, point_x: float, point_y: float) -> str:
    """PLANNED, not yet callable. Will produce a pixel-precise mask for the
    object at the given normalized (x, y) point using SAM or MM-OVSeg. See
    system_prompts/segmentation_sam/SYSTEM_PROMPT.md. Note: unlike the
    other tools here, real segmentation backs POST /api/segment directly
    (ui/DESIGN.md §2.5), not an agent tool call -- this stub is kept for
    documentation symmetry with the other not-ready models."""
    raise NotImplementedError("segmentation model is not integrated yet -- see system_prompts/segmentation_sam/")
