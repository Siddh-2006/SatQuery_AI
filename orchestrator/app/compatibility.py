"""
app/compatibility.py
======================
The authoritative "can we even attempt this?" check (`orchestrator/
DESIGN.md` §5 step 1 / §9's open item from `ui/DESIGN.md`). Runs BEFORE
the LLM is ever invoked, so an unsupported request fails fast and cheap
instead of burning a model call to discover what this module already
knows. Mirrors (but is stricter than, and is the real enforcement behind)
the frontend's own client-side checks in `ui/src/api/validateContextSet.ts`.

Every failure returns the exact `ApiErrorBody` shape `ui/DESIGN.md` §6.9
defines, so `api/query.py` can return it completely as-is.
"""
from typing import Optional

from tools.registry import is_task_supported


def check_query_compatible(context_set: dict) -> Optional[dict]:
    """Returns None if the request can proceed, or an `ApiErrorBody` dict
    to return immediately (as a non-2xx response) otherwise."""
    context_type = context_set["type"]
    items = context_set["items"]

    # -- Is there any ready tool at all for this context type? -----------
    # (bitemporal_pair / cross_modal_pair -> no change-detection or fusion
    # model exists yet; see DESIGN.md §4/§13.)
    if not is_task_supported(context_type):
        return _error(
            "unsupported_task",
            f"No specialist model is available yet for '{context_type}' queries. "
            "Only single-image analysis (VQA, captioning, grounding) is supported in this build.",
            {"contextType": context_type},
        )

    # -- Per-item checks (only relevant for "single", which is the only
    # type that passes the check above today) --------------------------
    for item in items:
        if item["kind"] == "uploaded_image":
            return _error(
                "incompatible_context",
                "Querying an uploaded image isn't supported yet -- the current model only understands "
                "patches from the indexed BigEarthNet dataset. You can still add the upload to context "
                "and inspect its preview, just not ask questions about it yet.",
                {"fileId": item.get("fileId")},
            )
        if item["kind"] == "patch" and item.get("bandSelection") == "sar_only":
            return _error(
                "incompatible_context",
                "SAR-only queries aren't supported by the current EOCaptioner model -- it always needs "
                "the optical (S2) bands present, SAR can only be added alongside them. "
                "Try 'Add full S1+S2 bands' or 'Add (default RGB)' instead.",
                {"patchId": item.get("patchId"), "bandSelection": "sar_only"},
            )

    return None


def wants_sar(context_set: dict) -> bool:
    """Whether SAR bands should be pulled in alongside optical for this
    query, per the active item's bandSelection (`ui/DESIGN.md` §2.3).
    Area selections and uploads have no bandSelection concept, so they
    never request SAR explicitly here."""
    for item in context_set["items"]:
        if item["kind"] == "patch" and item.get("bandSelection") == "full_bands":
            return True
    return False


def _error(code: str, message: str, details: dict) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}
