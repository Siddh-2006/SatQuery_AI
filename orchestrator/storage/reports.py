"""
storage/reports.py
====================
The "downloadable report" mandatory PS deliverable (`ui/DESIGN.md` §3.4).
A report is just a small JSON file written the moment a query finishes
(`app/response_builder.py` calls `write_report` right before returning),
and streamed back byte-for-byte by `GET /api/reports/:id` -- no
regeneration logic needed at download time, so a report never changes
after the fact even if the underlying data model does.
"""
import json
from pathlib import Path
from typing import Optional

from app.config import settings


def write_report(report_id: str, *, session_id: str, query: str, answer: str, evidence: list, confidence: float,
                  execution_trace: dict) -> None:
    """Writes one report as pretty-printed JSON -- plain text is fine for
    a hackathon deliverable; a PDF renderer would slot in here later
    without changing any caller."""
    payload = {
        "reportId": report_id,
        "sessionId": session_id,
        "query": query,
        "answer": answer,
        "evidence": evidence,
        "confidence": confidence,
        "executionTrace": execution_trace,
    }
    path = settings.report_store_dir / f"{report_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_report_bytes(report_id: str) -> Optional[bytes]:
    path: Path = settings.report_store_dir / f"{report_id}.json"
    if not path.exists():
        return None
    return path.read_bytes()
