"""
app/graph.py
==============
The orchestrator's agent loop, built as a LangGraph `StateGraph` -- see
`orchestrator/DESIGN.md` §5 for the full write-up of why this replaced an
earlier `langchain.agents.AgentExecutor` version, in short:

- `AgentExecutor` is LangChain's legacy agent runner; LangGraph is what
  the LangChain ecosystem now recommends for anything beyond the most
  trivial agent, which is also why the project asked to build this "in
  the lang ecosystem, latest version."
- The retry-on-malformed-output behaviour `gemma4_orchestrator_instructions.md`
  step 5 asks for (if a bbox call comes back "yes"/"no", retry once with a
  stricter template) is a real branch in the flow, not just "keep looping
  until the model says Final Answer" -- a graph expresses that directly as
  an edge; `AgentExecutor`'s fixed loop can't.
- Since this graph controls tool dispatch itself (see `execute_tools`
  below), it can hand a tool this turn's resolved patch files as a plain
  function argument -- no contextvar needed to smuggle that data past a
  fixed LLM-visible tool schema (compare the old `app/request_context.py`,
  now deleted).

Graph shape:

    check_compatibility --(rejected)--> reject --> END
           |(ok)
           v
    resolve_patches --(failed)--> reject --> END
           |(ok)
           v
      seed_prompt
           |
           v
    +--> agent_step --(final answer / step limit)--> compose_answer --> END
    |         |(tool call)
    |         v
    |   execute_tools
    |         |
    |         v
    +-- validate_observation
        (always loops back to agent_step -- either with a corrective nudge
         if the last tool observation looked malformed and we haven't
         retried yet, or plain, letting the model decide its next move)

Progress narration: each node calls `app/progress.report(...)` itself
(the same terminal+SSE mechanism as before, `app/status_bus.py`) rather
than being derived from LangGraph's own `.stream()` output -- deriving it
from `.stream()` would mean re-implementing the `add_messages` reducer's
merge logic by hand to reconstruct state between steps, which is more
risk for a hackathon-scale app than it's worth. Explicit calls, right
where the work happens, stay easy to follow.
"""
import json
import re
import uuid
from typing import Annotated, Callable, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from app import progress
from app.compatibility import check_query_compatible, wants_sar
from app.config import settings
from app.llm_gemini import build_gemini_chat_model
from app.llm_litert import LiteRTGemmaChat
from app.prompts import build_litert_system_message, build_system_preamble
from data.patch_index import ResolvedPatch, resolve_patch_for_query
from tools.registry import get_ready_tool_impls, get_ready_tool_schemas

MAX_AGENT_STEPS = 6
MALFORMED_RETRY_LIMIT = 1


class CompatibilityError(Exception):
    """Raised by `answer_query` when the graph's `check_compatibility` or
    `resolve_patches` node rejects the request. Carries the exact
    `ApiErrorBody` dict `api/query.py` returns as-is."""

    def __init__(self, error_body: dict):
        super().__init__(error_body["error"]["message"])
        self.error_body = error_body


class OrchestratorState(TypedDict):
    session_id: str
    query: str
    context_set: dict
    resolved_patches: dict[str, ResolvedPatch]
    # `add_messages` is LangGraph's standard reducer for a message list --
    # each node returns just the NEW messages it produced, and the graph
    # appends them (rather than every node needing to know/repeat the full
    # history, which is how plain TypedDict fields behave by default).
    messages: Annotated[list[BaseMessage], add_messages]
    tool_calls_made: list[dict]  # [{"name", "args", "observation"}, ...] -- for response_builder.py
    step_count: int
    malformed_retries: int
    error: dict | None  # ApiErrorBody, set by check_compatibility/resolve_patches on rejection
    final_answer: str | None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def node_check_compatibility(state: OrchestratorState) -> dict:
    progress.report(state["session_id"], "check_compatibility", "checking whether this context/task is supported")
    error = check_query_compatible(state["context_set"])
    return {"error": error}


def node_resolve_patches(state: OrchestratorState) -> dict:
    context_set = state["context_set"]
    progress.report(state["session_id"], "resolve_patches", f"context type={context_set['type']}")
    include_sar = wants_sar(context_set)
    resolved: dict[str, ResolvedPatch] = {}
    try:
        for item in context_set["items"]:
            if item["kind"] == "patch":
                patch_id = item["patchId"]
            elif item["kind"] == "area_selection":
                if not item["resolvedPatchIds"]:
                    continue
                patch_id = item["resolvedPatchIds"][0]
            else:
                continue
            if patch_id not in resolved:
                resolved[patch_id] = resolve_patch_for_query(patch_id, include_sar=include_sar)
    except (KeyError, ValueError) as e:
        return {"error": {"error": {"code": "incompatible_context", "message": str(e), "details": {}}}}
    return {"resolved_patches": resolved}


def node_seed_prompt(state: OrchestratorState) -> dict:
    """Builds the initial [system, human] message pair -- one time, at the
    start of the turn. Everything after this is agent_step/execute_tools
    appending to the same running `messages` list."""
    tools = get_ready_tool_schemas()
    if settings.llm_backend == "gemini":
        system_text = build_system_preamble(state["resolved_patches"])
    else:
        system_text = build_litert_system_message(state["resolved_patches"], tools)
    return {"messages": [SystemMessage(content=system_text), HumanMessage(content=state["query"])]}


def node_agent_step(state: OrchestratorState) -> dict:
    progress.report(state["session_id"], "agent_step", f"agent thinking (step {state['step_count'] + 1}/{MAX_AGENT_STEPS})")
    if settings.llm_backend == "gemini":
        ai_message = _gemini_step(state["messages"])
    else:
        ai_message = _litert_step(state["messages"])
    return {"messages": [ai_message], "step_count": state["step_count"] + 1}


def _gemini_step(messages: list[BaseMessage]) -> AIMessage:
    """Gemini has native function calling -- bind the ready tools and let
    the API itself decide whether to call one. `.bind_tools()` makes the
    returned AIMessage's `.tool_calls` populate automatically when it
    chooses to call something."""
    llm = build_gemini_chat_model().bind_tools(get_ready_tool_schemas())
    return llm.invoke(messages)


def _litert_step(messages: list[BaseMessage]) -> AIMessage:
    """No native tool calling here -- render the whole conversation as one
    text prompt (system + question + prior Thought/Action/Observation
    turns), ask the local Gemma model to continue it, and parse its JSON
    blob response back into a structured tool call (or a plain final
    answer). This is the hand-rolled equivalent of what LangChain's
    (legacy) `create_structured_chat_agent` did automatically."""
    llm = LiteRTGemmaChat(server_url=settings.litert_server_url)
    prompt_text = _render_litert_transcript(messages)
    raw_text = llm.invoke(prompt_text).content

    action, action_input = _parse_json_blob(raw_text)
    if action is None or action == "Final Answer":
        answer_text = action_input if isinstance(action_input, str) and action_input else raw_text
        return AIMessage(content=answer_text)

    call_id = f"call_{uuid.uuid4().hex[:8]}"
    args = action_input if isinstance(action_input, dict) else {}
    return AIMessage(content=raw_text, tool_calls=[{"name": action, "args": args, "id": call_id}])


def _render_litert_transcript(messages: list[BaseMessage]) -> str:
    """messages[0] is the SystemMessage (mission + tools + format
    instructions), messages[1] the HumanMessage (the user's question);
    everything after alternates AIMessage (a prior Thought/Action) and
    ToolMessage (its Observation) -- rendered back into the
    Question/Thought/Action/Observation transcript shape the system
    message's format instructions describe."""
    parts = [messages[0].content, "", f"Question: {messages[1].content}"]
    for message in messages[2:]:
        if isinstance(message, AIMessage):
            parts.append(f"Thought: {message.content}" if message.content else "Thought:")
            if message.tool_calls:
                call = message.tool_calls[0]
                blob = json.dumps({"action": call["name"], "action_input": call["args"]})
                parts.append(f"Action:\n```\n{blob}\n```")
        elif isinstance(message, ToolMessage):
            parts.append(f"Observation: {message.content}")
    parts.append("Thought:")
    return "\n".join(parts)


_JSON_BLOB_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_blob(text: str) -> tuple[str | None, object]:
    """Extracts and parses the first `{...}` JSON object found in the
    model's raw output. Returns (None, raw_text) if nothing parseable is
    found -- treated as a plain final answer rather than a crash, since a
    small local model occasionally forgets the JSON-blob format and just
    answers in plain English."""
    match = _JSON_BLOB_RE.search(text)
    if not match:
        return None, text.strip()
    try:
        blob = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, text.strip()
    return blob.get("action"), blob.get("action_input")


def node_execute_tools(state: OrchestratorState) -> dict:
    last = state["messages"][-1]
    assert isinstance(last, AIMessage) and last.tool_calls  # route_after_agent only sends us here when true
    impls = get_ready_tool_impls()

    tool_messages: list[ToolMessage] = []
    calls_made: list[dict] = []
    for call in last.tool_calls:
        name, args, call_id = call["name"], call["args"], call["id"]
        progress.report(state["session_id"], "execute_tools", f"calling {name}({args})")

        impl = impls.get(name)
        if impl is None:
            observation = f"ERROR: unknown tool '{name}'"
        else:
            observation = impl(
                args.get("patch_id", ""),
                args.get("instruction", ""),
                state["resolved_patches"],
                settings.eocaptioner_url,
            )
        progress.report(state["session_id"], "tool_result", observation[:200])

        tool_messages.append(ToolMessage(content=observation, tool_call_id=call_id, name=name))
        calls_made.append({"name": name, "args": args, "observation": observation})

    return {"messages": tool_messages, "tool_calls_made": state["tool_calls_made"] + calls_made}


def node_validate_observation(state: OrchestratorState) -> dict:
    """Implements `gemma4_orchestrator_instructions.md` step 5: if the most
    recent tool call's raw observation doesn't match the shape its
    instruction asked for (an MCQ that didn't come back as a letter, a
    bbox request that came back with no coordinates), nudge the model to
    retry once with a stricter template -- rather than silently accepting
    (and confidently rephrasing) a wrong answer."""
    last_call = state["tool_calls_made"][-1] if state["tool_calls_made"] else None
    if last_call and _looks_malformed(last_call) and state["malformed_retries"] < MALFORMED_RETRY_LIMIT:
        progress.report(state["session_id"], "validate_observation", f"'{last_call['name']}' looked malformed -- retrying once")
        nudge = HumanMessage(
            content=(
                "That tool observation doesn't look right for the instruction shape you used. "
                "Re-read your tool's instructions and retry with a more strictly-templated instruction, "
                "or if you're not confident a retry will help, tell the user honestly that this couldn't be answered."
            )
        )
        return {"messages": [nudge], "malformed_retries": state["malformed_retries"] + 1}
    return {}


def _looks_malformed(call: dict) -> bool:
    args = call["args"] if isinstance(call["args"], dict) else {}
    instruction = args.get("instruction", "")
    observation = call["observation"]
    if observation.startswith("ERROR:"):
        return False  # a clean, honest tool-side error isn't "malformed" -- nothing to retry
    if re.search(r"\ba\)\s", instruction) and not re.match(r"^[a-e]\b", observation.strip(), re.IGNORECASE):
        return True  # an MCQ instruction should get back a lettered answer
    if ("<point>" in instruction or "<ref>" in instruction) and not re.search(r"[\d.]+\s+[\d.]+", observation):
        return True  # a bbox instruction should get back coordinate-shaped numbers
    return False


def node_compose_answer(state: OrchestratorState) -> dict:
    progress.report(state["session_id"], "compose_answer", "")
    last_final = next(
        (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and not m.tool_calls), None
    )
    answer = last_final.content if last_final and last_final.content else "I couldn't produce a reliable answer for this."
    return {"final_answer": answer}


def node_reject(state: OrchestratorState) -> dict:
    return {}


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------
def route_after_compatibility(state: OrchestratorState) -> str:
    return "reject" if state["error"] else "resolve_patches"


def route_after_resolve(state: OrchestratorState) -> str:
    return "reject" if state.get("error") else "seed_prompt"


def route_after_agent(state: OrchestratorState) -> str:
    if state["step_count"] >= MAX_AGENT_STEPS:
        return "compose_answer"
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "execute_tools"
    return "compose_answer"


def build_graph():
    graph = StateGraph(OrchestratorState)
    graph.add_node("check_compatibility", node_check_compatibility)
    graph.add_node("resolve_patches", node_resolve_patches)
    graph.add_node("seed_prompt", node_seed_prompt)
    graph.add_node("agent_step", node_agent_step)
    graph.add_node("execute_tools", node_execute_tools)
    graph.add_node("validate_observation", node_validate_observation)
    graph.add_node("compose_answer", node_compose_answer)
    graph.add_node("reject", node_reject)

    graph.set_entry_point("check_compatibility")
    graph.add_conditional_edges(
        "check_compatibility", route_after_compatibility, {"reject": "reject", "resolve_patches": "resolve_patches"}
    )
    graph.add_conditional_edges("resolve_patches", route_after_resolve, {"reject": "reject", "seed_prompt": "seed_prompt"})
    graph.add_edge("seed_prompt", "agent_step")
    graph.add_conditional_edges(
        "agent_step", route_after_agent, {"execute_tools": "execute_tools", "compose_answer": "compose_answer"}
    )
    graph.add_edge("execute_tools", "validate_observation")
    # Always loops back to agent_step -- either with a retry nudge freshly
    # appended (see node_validate_observation) or without one, letting the
    # model decide its next move (another tool call, or Final Answer).
    graph.add_edge("validate_observation", "agent_step")
    graph.add_edge("compose_answer", END)
    graph.add_edge("reject", END)

    return graph.compile()


# Compiled once and reused -- a LangGraph `CompiledGraph` holds no
# per-request state (that all lives in the state dict passed to
# `.invoke()`), so there's no reason to rebuild it on every query.
_compiled_graph = None


def _get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


def run_graph(session_id: str, query: str, context_set: dict) -> OrchestratorState:
    """Runs the full graph for one turn and returns its final state.
    Raises `CompatibilityError` if `check_compatibility`/`resolve_patches`
    rejected the request -- `api/query.py` catches that specifically to
    return the right HTTP status instead of a generic 500."""
    initial_state: OrchestratorState = {
        "session_id": session_id,
        "query": query,
        "context_set": context_set,
        "resolved_patches": {},
        "messages": [],
        "tool_calls_made": [],
        "step_count": 0,
        "malformed_retries": 0,
        "error": None,
        "final_answer": None,
    }
    final_state = _get_graph().invoke(initial_state)
    if final_state.get("error"):
        raise CompatibilityError(final_state["error"])
    return final_state
