"""
tools/eocaptioner_tool.py
===========================
The ONE real, working tool (`orchestrator/DESIGN.md` §4): calls the
existing EOCaptioner model server (`server/serve.py`, TerraFM vision
encoder + a projected LLM) to answer a correctly-templated instruction
about one satellite patch.

Two things live here, and they're deliberately separate:

- `query_eocaptioner` -- a `@tool`-decorated function whose only job is to
  give LangChain a name/description/args-schema to work with: rendering
  the tool's JSON schema into the local Gemma prompt (`app/prompts.py`)
  and binding it natively for Gemini (`llm.bind_tools(...)`,
  `app/graph.py`). Its *body* is never actually executed in production --
  `app/graph.py`'s `execute_tools` node calls `run_eocaptioner` below
  directly instead, because doing so lets it pass this turn's resolved
  patch files straight in as a normal function argument, rather than
  needing a global/contextvar to smuggle that data past a fixed
  `patch_id, instruction` tool-calling schema (the LLM only ever sees
  those two arguments -- it never sees file paths). This is one of the
  concrete simplifications moving from `AgentExecutor` to a hand-built
  LangGraph graph enabled: the graph controls tool dispatch itself, so it
  can just... pass the extra context in.
- `run_eocaptioner` -- the real implementation, a plain function.

The tool's LLM-visible schema is intentionally IDENTICAL to the one
defined in `system_prompts/eocaptioner_s1_s2/SYSTEM_PROMPT.md` (which is
`gemma4_orchestrator_instructions.md` verbatim) -- `patch_id` and
`instruction`, nothing else -- because that document is the one the model
was actually written/tuned against for exactly this tool-calling shape.
"""
import logging

import requests
from langchain_core.tools import tool

from data.patch_index import ResolvedPatch

logger = logging.getLogger("orchestrator")


@tool
def query_eocaptioner(patch_id: str, instruction: str) -> str:
    """Sends one correctly-templated instruction to the fine-tuned EOCaptioner
    model for a given satellite patch and returns its raw text answer.

    EOCaptioner only understands 4 exact template shapes -- captioning,
    yes/no binary, lettered MCQ, and point/ref-anchored bounding box. See
    your system prompt's EOCaptioner section for the exact phrasing rules;
    off-template instructions silently produce wrong/default answers.

    Args:
        patch_id: The satellite patch identifier this turn's context gave you
            (e.g. "KOS-34TEN-000-041"). Must be one of the patch_id values
            you were told about -- inventing one will fail.
        instruction: Instruction phrased in one of the 4 required template
            shapes.
    """
    raise RuntimeError(
        "query_eocaptioner is schema-only (see this file's module docstring) -- "
        "it's invoked via app/graph.py's execute_tools node calling run_eocaptioner() "
        "directly, never through this LangChain tool wrapper's own body."
    )


def run_eocaptioner(
    patch_id: str,
    instruction: str,
    resolved_patches: dict[str, ResolvedPatch],
    eocaptioner_url: str,
) -> str:
    """The real implementation, called directly by `app/graph.py`'s
    `execute_tools` node with this turn's already-resolved patch files.
    Never raises for an expected failure mode (unknown patch, no optical
    imagery, the eocaptioner service being down) -- returns an
    "ERROR: ..." string instead, so the calling LLM sees it as a normal
    tool observation and can react (per
    `gemma4_orchestrator_instructions.md` step 5: retry once with a
    stricter template, or tell the user honestly) rather than the whole
    turn crashing.
    """
    if patch_id not in resolved_patches:
        return (
            f"ERROR: patch_id '{patch_id}' was not one of the patches resolved for this turn. "
            "Use exactly the patch_id given to you in the context above."
        )

    resolved = resolved_patches[patch_id]
    if resolved.s2_dir is None:
        return f"ERROR: patch '{patch_id}' has no optical imagery available; EOCaptioner cannot process it."

    payload = {
        "s2_dir": str(resolved.s2_dir),
        "patch_id": resolved.s2_patch_id,
        "prompt": instruction,
    }
    if resolved.s1_dir is not None:
        payload["s1_dir"] = str(resolved.s1_dir)
        payload["s1_patch_id"] = resolved.s1_patch_id

    try:
        response = requests.post(f"{eocaptioner_url}/generate", json=payload, stream=True, timeout=120)
        response.raise_for_status()
        answer = "".join(chunk.decode("utf-8", errors="replace") for chunk in response.iter_content(chunk_size=None))
    except requests.RequestException as e:
        logger.warning("eocaptioner call failed: %s", e)
        return f"ERROR: the EOCaptioner service could not be reached or failed ({e}). Tell the user the model is temporarily unavailable."

    return answer.strip()
