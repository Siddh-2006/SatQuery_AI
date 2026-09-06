"""
tools/registry.py
===================
The single place that decides which tools the LLM agent is actually
allowed to call. Reads each specialist model's `capabilities.json` under
`system_prompts/` (`orchestrator/DESIGN.md` §4/§8) and only exposes the
ones marked `"status": "ready"` -- today, that's exactly one:
`query_eocaptioner`.

Two separate things are exposed per ready tool (see
`tools/eocaptioner_tool.py`'s module docstring for why they're split):

- `get_ready_tool_schemas()` -- the LangChain `@tool` objects, used only
  for their name/description/args-schema (prompt rendering for the local
  Gemma backend, `.bind_tools()` for Gemini). Never actually invoked.
- `get_ready_tool_impls()` -- plain callables
  `(patch_id, instruction, resolved_patches, eocaptioner_url) -> str`
  that `app/graph.py`'s `execute_tools` node calls directly.

Why gate on a JSON file instead of just hardcoding "here are the ready
tools" in Python: the moment a new model is ready, flipping
`capabilities.json`'s `status` field is the whole "turn this tool on"
step (plus writing the real tool function, if it isn't `future_tools.py`'s
placeholder anymore) -- nobody has to go hunting through agent code to
find where the tool list is assembled.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from langchain_core.tools import BaseTool

from tools.eocaptioner_tool import query_eocaptioner, run_eocaptioner

_SYSTEM_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "system_prompts"

# tool_name -> (schema object, plain implementation callable), for every
# tool that HAS a real implementation. A model whose capabilities.json
# exists but isn't in this dict yet (i.e. everything in future_tools.py)
# simply can't become "ready" until someone adds its real tool function
# here -- a deliberate safety net against flipping a status flag and
# forgetting to also write the code.
_REGISTERED: dict[str, tuple[BaseTool, Callable]] = {
    "query_eocaptioner": (query_eocaptioner, run_eocaptioner),
}


@dataclass(frozen=True)
class ToolInfo:
    tool_name: str
    status: str  # "ready" | "not_ready"
    model_name: str
    role: str
    system_prompt_dir: Path


def _load_all_tool_infos() -> list[ToolInfo]:
    infos = []
    for subdir in sorted(_SYSTEM_PROMPTS_DIR.iterdir()):
        capabilities_path = subdir / "capabilities.json"
        if not capabilities_path.exists():
            continue
        spec = json.loads(capabilities_path.read_text(encoding="utf-8"))
        infos.append(
            ToolInfo(
                tool_name=spec["tool_name"],
                status=spec["status"],
                model_name=spec["model_name"],
                role=spec["role"],
                system_prompt_dir=subdir,
            )
        )
    return infos


def _ready_tool_names() -> list[str]:
    return [info.tool_name for info in _load_all_tool_infos() if info.status == "ready" and info.tool_name in _REGISTERED]


def get_ready_tool_schemas() -> list[BaseTool]:
    """The LangChain tool objects to render/bind this run -- schema only,
    see this module's docstring."""
    return [_REGISTERED[name][0] for name in _ready_tool_names()]


def get_ready_tool_impls() -> dict[str, Callable]:
    """tool_name -> plain callable, for `execute_tools` to dispatch to."""
    return {name: _REGISTERED[name][1] for name in _ready_tool_names()}


def get_ready_tool_infos() -> list[ToolInfo]:
    """Metadata (model name, role) for every ready tool -- used to build
    `executionTrace.modelsUsed` (`app/response_builder.py`) and the system
    prompt's per-tool instructions (`app/prompts.py`)."""
    return [info for info in _load_all_tool_infos() if info.status == "ready" and info.tool_name in _REGISTERED]


def is_task_supported(context_type: str) -> bool:
    """Quick pre-flight check `app/compatibility.py` uses BEFORE spending an
    LLM call: is there at least one ready tool whose capabilities.json says
    it can handle this context type at all? (`ui/DESIGN.md` §4.1's three
    context types map roughly 1:1 onto which specialist tool is needed.)"""
    for subdir in sorted(_SYSTEM_PROMPTS_DIR.iterdir()):
        capabilities_path = subdir / "capabilities.json"
        if not capabilities_path.exists():
            continue
        spec = json.loads(capabilities_path.read_text(encoding="utf-8"))
        if spec["status"] != "ready" or spec["tool_name"] not in _REGISTERED:
            continue
        if context_type in spec.get("supported_context_types", []):
            return True
    return False
