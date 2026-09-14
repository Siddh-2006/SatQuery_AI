"""
app/demo_placeholders.py
==========================
The fixed stand-in answers used when a request needs a specialist model
that isn't integrated yet (`orchestrator/DESIGN.md` §4/§13 -- everything
in `tools/future_tools.py`, i.e. change detection, cross-modal fusion and
segmentation).

WHY THIS EXISTS (demo branch): without it, those requests are rejected at
`app/compatibility.py` with a 422 before the LLM is ever called, which is
the honest production behaviour but means whole sections of the UI can't
be walked through end-to-end. With `DEMO_PLACEHOLDERS=true` the same
requests come back as a normal, successful answer carrying one of the
fixed texts below, so a demo can follow the full happy path -- context
set -> query -> answer -> evidence -> report -- for every context type.

TWO RULES THIS FILE KEEPS, deliberately:

1. Every text says plainly, in its first line, that it is a placeholder
   and that the model is not yet integrated. A canned paragraph that
   *reads* like a real analysis would be indistinguishable from genuine
   model output in a screenshot, which is exactly the thing not to ship.
2. The texts are constants, never model-generated. A demo wants the same
   words every time, and a local 2.5GB Gemma paraphrasing "I can't do
   this" differently on each run is precisely what this avoids.

The answers are keyed by WHICH MISSING MODEL the request needed, not by
which error the compatibility check raised, so that wiring up a real
backend later means deleting one entry here and flipping its
`capabilities.json` status -- with nothing else to hunt down.
"""
from tools.registry import get_tool_info_by_name

# Prefix shared by every placeholder, so the "this is not a real result"
# signal is in a fixed, greppable place rather than reworded per case.
_PREFIX = "[Demo placeholder — model not yet integrated]"

# placeholder key -> (tool_name it stands in for, the fixed answer body).
# The tool_name is looked up in the registry at render time so the planned
# model's display name comes from its capabilities.json and can't drift
# out of sync with what the execution trace reports.
_PLACEHOLDERS: dict[str, tuple[str, str]] = {
    "bitemporal_pair": (
        "query_change_detection",
        "Comparing two captures of the same location is a change-detection task, and the "
        "change-detection specialist is still being trained — so there is no real analysis "
        "behind this reply.\n\n"
        "Once it is wired in, this is where you would see what changed between the two dates: "
        "new or demolished built-up area, water extent moving, vegetation gained or lost, with "
        "the changed regions outlined on the map as evidence you can hover.\n\n"
        "Single-image questions are answered by a real model today — add just one patch to "
        "context and ask about it to see the genuine pipeline run.",
    ),
    "cross_modal_pair": (
        "query_cross_modal_fusion",
        "Reasoning jointly over a co-registered optical + SAR pair needs the cross-modal fusion "
        "specialist, which is not integrated yet — so there is no real analysis behind this reply.\n\n"
        "Once it is wired in, this is where the optical and radar views would be read together: "
        "SAR seeing through the cloud and haze that blinds the optical bands, optical supplying the "
        "surface detail SAR cannot, and the answer drawing on whichever modality actually carries "
        "the evidence.\n\n"
        "Single-image questions are answered by a real model today — add just one patch to "
        "context and ask about it to see the genuine pipeline run.",
    ),
    "segmentation": (
        "query_segmentation",
        "Pixel-precise segmentation needs the segmentation specialist (SAM / MM-OVSeg), which is "
        "not integrated yet — so the outline you see is a fixed stand-in shape, not a real mask.\n\n"
        "Once it is wired in, clicking a point would return the actual boundary of the object under "
        "your cursor — a lake edge, a field parcel, a building footprint — instead of this box.\n\n"
        "The bounding boxes that come back from single-image grounding questions ARE real model "
        "output, and are a good way to see genuine localisation today.",
    ),
    "uploaded_image": (
        "query_eocaptioner",
        "Questions about an uploaded image are not supported yet — so there is no real analysis "
        "behind this reply.\n\n"
        "The current model reads patches from the indexed BigEarthNet dataset, where every band is "
        "already calibrated and co-registered the way it was trained on; an arbitrary upload has "
        "none of that, and handing it over anyway would produce confident nonsense.\n\n"
        "Pick a patch from the map and ask the same question to see the genuine pipeline run.",
    ),
    "sar_only": (
        "query_eocaptioner",
        "A SAR-only query isn't something the current model can answer — so there is no real "
        "analysis behind this reply.\n\n"
        "EOCaptioner always needs the optical (S2) bands present; SAR is additive alongside them, "
        "never a standalone input. Reading radar on its own is what the cross-modal fusion "
        "specialist will be for, and that one is still being trained.\n\n"
        "Switch this patch to 'Add full S1+S2 bands' and ask again to see the genuine pipeline run.",
    ),
}

# Used by app/prompts.py when no specific key applies: the agent has a
# ready tool and valid context, but the user asked it for something that
# tool fundamentally cannot do (segmentation, change over time, ...).
GENERIC_KEY = "generic"
_GENERIC = (
    "That needs a specialist model that isn't integrated into this build yet, so there is no real "
    "analysis behind this reply. The models still being trained cover change detection over time, "
    "joint optical + SAR reasoning, and pixel-precise segmentation. Single-image questions — "
    "description, yes/no, multiple choice, and 'where is X' bounding boxes — run against a real "
    "model today."
)


def placeholder_answer(key: str) -> str:
    """The fixed answer text for one missing-model case, prefix included.
    Unknown keys fall back to the generic text rather than raising: a demo
    build failing *because* its fallback is missing would be absurd."""
    if key == GENERIC_KEY or key not in _PLACEHOLDERS:
        return f"{_PREFIX} {_GENERIC}"
    return f"{_PREFIX} {_PLACEHOLDERS[key][1]}"


def placeholder_model_used(key: str) -> dict | None:
    """The `executionTrace.modelsUsed` entry for a placeholder answer --
    the model that WOULD have handled this, named from its own
    capabilities.json and explicitly flagged as not real.

    Reported rather than left empty on purpose: the execution trace is the
    PS's auditable summary, and "this answer came from nothing, and here is
    which model it was standing in for" is the honest thing for it to say."""
    if key not in _PLACEHOLDERS:
        return None
    info = get_tool_info_by_name(_PLACEHOLDERS[key][0])
    if info is None:
        return None
    return {"name": f"{info.model_name} — PLACEHOLDER, not actually run", "role": info.role}


def placeholder_task(key: str) -> str:
    """`executionTrace.task` for a placeholder answer, matching the task
    vocabulary ui/DESIGN.md uses for the real ones."""
    return {
        "bitemporal_pair": "change_vqa",
        "cross_modal_pair": "cross_modal_fusion",
        "segmentation": "segmentation",
        "uploaded_image": "vqa",
        "sar_only": "vqa",
    }.get(key, "vqa")
