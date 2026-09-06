"""
app/prompts.py
================
Builds the plain-text/message content the agent runs with. Now that
`app/graph.py` constructs LangChain messages (`SystemMessage`,
`HumanMessage`, ...) by hand instead of going through a LangChain
`PromptTemplate`/`ChatPromptTemplate`, everything in this file is just
ordinary Python string-building -- no template engine re-parses these
strings looking for `{placeholders}`, so unlike the previous
`AgentExecutor`-based version of this file, there is no brace-escaping
concern here at all (worth calling out explicitly since it *was* a real
gotcha before: the tool system prompts below quote JSON schemas, curly
braces and all).

- `build_system_preamble()` -- the mission blurb + this turn's resolved
  patch context + every ready tool's own `SYSTEM_PROMPT.md`. Used as-is
  for the Gemini backend (native tool calling needs no extra formatting
  instructions in the prompt -- the API handles that).
- `build_litert_system_message()` -- the above, PLUS the JSON-blob
  tool-calling format instructions Gemma needs since it has no native
  function calling (`orchestrator/DESIGN.md` §3.2).
"""
from langchain_core.tools import BaseTool
from langchain_core.tools.render import render_text_description_and_args

from data.patch_index import ResolvedPatch, get_patch
from tools.registry import get_ready_tool_infos

_MISSION_BLURB = """\
You are the orchestrator for SatQuery AI, an agentic assistant for analysing \
satellite imagery through natural-language questions. You do not look at \
images yourself -- you decide which specialist tool (if any) can answer the \
user's question, call it with a correctly-shaped instruction, and turn its \
raw answer into a clear, natural response.

Rules:
- If a tool is available for this context, use it -- do not guess an answer \
from general knowledge about what a satellite image "probably" shows.
- Only ever pass a patch_id that was explicitly given to you below -- never \
invent one.
- If a question doesn't map onto anything a tool can do, say so plainly \
rather than forcing a bad answer.
- Keep your final answer natural and concise -- translate terse raw model \
output (e.g. a bare "c" or normalized coordinates) into plain language, the \
way the examples in the tool's own instructions below show.
"""


def _patch_context_blurb(resolved_patches: dict[str, ResolvedPatch]) -> str:
    """Describes exactly which patch_id(s) are available this turn and what
    each one actually has (optical only, or optical+SAR) -- so the agent
    never has to guess an id or assume a modality that wasn't resolved."""
    if not resolved_patches:
        return "No image context is available for this turn."
    lines = ["Available patch(es) for this turn:"]
    for patch_id, resolved in resolved_patches.items():
        footprint = get_patch(patch_id)
        modalities = "optical" + ("+SAR" if resolved.s1_dir else "")
        label = footprint.label if footprint else patch_id
        lines.append(f"- patch_id=\"{patch_id}\" ({label}) -- modalities available: {modalities}")
    return "\n".join(lines)


def build_system_preamble(resolved_patches: dict[str, ResolvedPatch]) -> str:
    """Used directly as the Gemini backend's system message -- native tool
    calling means no extra "how to format a tool call" text is needed."""
    sections = [_MISSION_BLURB, _patch_context_blurb(resolved_patches)]
    for info in get_ready_tool_infos():
        prompt_path = info.system_prompt_dir / "SYSTEM_PROMPT.md"
        if prompt_path.exists():
            sections.append(f"--- Instructions for tool `{info.tool_name}` ---\n{prompt_path.read_text(encoding='utf-8')}")
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Local Gemma (LiteRT) backend -- no native function-calling, and
# query_eocaptioner takes two named arguments, so the model is asked to
# reply with a JSON blob ({"action": tool_name, "action_input": {...}})
# that app/graph.py's litert agent-step node parses back into a structured
# tool call. Same idea LangChain's (now-legacy) `create_structured_chat_agent`
# used, written out by hand here so app/graph.py has full control over the
# loop (retry-on-malformed-output, step limits) instead of it being buried
# inside a prebuilt agent runner.
# ---------------------------------------------------------------------------
def _json_blob_format_instructions(tools: list[BaseTool]) -> str:
    tool_names = ", ".join(t.name for t in tools)
    tool_descriptions = render_text_description_and_args(tools)
    return f"""
You have access to the following tools:

{tool_descriptions}

Respond with a JSON blob to specify which tool to use, in exactly this shape:
```
{{"action": "$TOOL_NAME", "action_input": {{...tool parameters as a JSON object...}}}}
```
Valid "action" values: "Final Answer" (to respond directly to the user) or one of [{tool_names}].
Provide only ONE action per JSON blob, and nothing outside the JSON blob itself.

When you're ready to answer the user directly, respond with:
```
{{"action": "Final Answer", "action_input": "your final answer to the user, phrased naturally"}}
```
"""


def build_litert_system_message(resolved_patches: dict[str, ResolvedPatch], tools: list[BaseTool]) -> str:
    return build_system_preamble(resolved_patches) + "\n\n" + _json_blob_format_instructions(tools)
