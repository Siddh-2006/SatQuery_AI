"""
app/response_builder.py
=========================
Turns the LangGraph run's final state (`app/graph.py`'s `OrchestratorState`
-- specifically `final_answer` and `tool_calls_made`) into the exact
`QueryResponse` shape `ui/DESIGN.md` §6.2 defines: `answer`,
`groundedSpans`, `evidence`, `confidence`, `executionTrace`, `reportUrl`.

This is the one place that interprets EOCaptioner's sometimes-terse raw
output (e.g. a bounding box call returning "[0.3 0.0, 1.0 1.0]") into a
structured `GroundingEvidence` entry -- everything else in the codebase
only ever sees the shaped result.
"""
import re
import uuid

from app.config import settings
from storage import reports as report_store
from tools.registry import get_ready_tool_infos

# Matches EOCaptioner's raw bounding-box answer shape, e.g.
# "[0.30 0.00, 1.00 1.00]" -- see gemma4_orchestrator_instructions.md's
# worked example. Four floats, order x0 y0, x1 y1.
_BBOX_RE = re.compile(r"\[?\s*([\d.]+)\s+([\d.]+)\s*,\s*([\d.]+)\s+([\d.]+)\s*\]?")


def _classify_task(last_instruction: str) -> str:
    """Best-effort task label for `executionTrace.task`, from the phrasing
    of the last instruction sent to EOCaptioner -- mirrors the 4 template
    shapes `gemma4_orchestrator_instructions.md` defines."""
    if "<point>" in last_instruction or "<ref>" in last_instruction:
        return "grounding"
    if last_instruction.strip().startswith("Describe this satellite image"):
        return "captioning"
    if re.search(r"\ba\)\s", last_instruction):
        return "vqa_mcq"
    return "vqa"


def _extract_bbox_evidence(patch_id: str, raw_observation: str, label: str) -> dict | None:
    match = _BBOX_RE.search(raw_observation)
    if not match:
        return None
    x0, y0, x1, y1 = (float(g) for g in match.groups())
    return {
        "id": f"ev_{uuid.uuid4().hex[:8]}",
        "patchId": patch_id,
        "kind": "bbox",
        "geometry": [x0, y0, x1, y1],
        "label": label,
    }


def build_query_response(*, session_id: str, query: str, state: dict) -> dict:
    """`state` is `app/graph.py`'s final `OrchestratorState` after a
    successful run (no `error` key set) -- specifically `final_answer` and
    `tool_calls_made` (`[{"name", "args", "observation"}, ...]`)."""
    answer: str = state["final_answer"]
    calls = state["tool_calls_made"]

    evidence = []
    last_instruction = ""
    for call in calls:
        args = call["args"] if isinstance(call["args"], dict) else {}
        patch_id = args.get("patch_id")
        instruction = args.get("instruction", "")
        if instruction:
            last_instruction = instruction
        bbox = _extract_bbox_evidence(patch_id or "unknown", call["observation"], instruction[:60] or "detected region")
        if bbox:
            evidence.append(bbox)

    task = _classify_task(last_instruction) if last_instruction else "vqa"
    models_used = [{"name": info.model_name, "role": info.role} for info in get_ready_tool_infos()] if calls else []

    report_id = f"rep_{uuid.uuid4().hex[:10]}"
    execution_trace = {
        "task": task,
        "modelsUsed": models_used,
        "parameters": {"toolCalls": len(calls)},
    }

    report_store.write_report(
        report_id,
        session_id=session_id,
        query=query,
        answer=answer,
        evidence=evidence,
        confidence=settings.placeholder_confidence,
        execution_trace=execution_trace,
    )

    return {
        "answer": answer,
        "groundedSpans": [],  # honest: no reliable text-span grounding yet, see DESIGN.md §13
        "evidence": evidence,
        "confidence": settings.placeholder_confidence,
        "executionTrace": execution_trace,
        "reportUrl": f"/api/reports/{report_id}",
    }
