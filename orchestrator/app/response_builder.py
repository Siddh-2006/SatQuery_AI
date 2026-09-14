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
from app.demo_placeholders import placeholder_model_used, placeholder_task
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


def _build_placeholder_response(*, session_id: str, query: str, answer: str, placeholder_key: str) -> dict:
    """The `QueryResponse` for a demo-mode placeholder (`app/graph.py`'s
    `placeholder_answer` node). Same shape as a real one -- the UI can't
    tell the difference structurally, and shouldn't have to -- but with
    every field telling the truth about what produced it:

    - `evidence` is empty: there is no real detection to draw on the map.
    - `confidence` is 0.0, not the usual placeholder constant. A stand-in
      answer has no confidence in any sense, and showing the same 0.75 a
      genuine answer carries would be the one genuinely misleading thing
      this feature could do.
    - `executionTrace.parameters.placeholder` is the machine-readable flag;
      `modelsUsed` names the model that WOULD have answered, marked as not
      actually run.

    The written report gets all of this too, so a downloaded PDF/JSON can
    never be mistaken for a record of a real run.
    """
    models_used = placeholder_model_used(placeholder_key)
    execution_trace = {
        "task": placeholder_task(placeholder_key),
        "modelsUsed": [models_used] if models_used else [],
        "parameters": {"toolCalls": 0, "placeholder": True, "placeholderReason": placeholder_key},
    }

    report_id = f"rep_{uuid.uuid4().hex[:10]}"
    report_store.write_report(
        report_id,
        session_id=session_id,
        query=query,
        answer=answer,
        evidence=[],
        confidence=0.0,
        execution_trace=execution_trace,
    )

    return {
        "answer": answer,
        "groundedSpans": [],
        "evidence": [],
        "confidence": 0.0,
        "executionTrace": execution_trace,
        "reportUrl": f"/api/reports/{report_id}",
    }


def build_query_response(*, session_id: str, query: str, state: dict) -> dict:
    """`state` is `app/graph.py`'s final `OrchestratorState` after a
    successful run (no `error` key set) -- specifically `final_answer` and
    `tool_calls_made` (`[{"name", "args", "observation"}, ...]`)."""
    answer: str = state["final_answer"]
    calls = state["tool_calls_made"]

    # Demo-mode placeholder: no tool ran and no model was called, so the
    # trace must say that rather than inheriting the "real answer" shape
    # below (which would credit EOCaptioner for text it never produced).
    placeholder_key = state.get("placeholder_key")
    if placeholder_key:
        return _build_placeholder_response(
            session_id=session_id, query=query, answer=answer, placeholder_key=placeholder_key
        )

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
