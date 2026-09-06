"""
app/llm_litert.py
===================
A LangChain `BaseChatModel` that talks to the small standalone
`litert_server` microservice (`orchestrator/litert_server/server.py`)
instead of loading the local Gemma model in-process -- see
`orchestrator/DESIGN.md` §3.1 for why that split exists.

How this gets used (`app/graph.py`'s `_litert_step`): the whole
conversation-so-far (system prompt + question + prior Thought/Action/
Observation turns) is rendered into ONE big string before ever reaching
this class, so `_generate` below only ever needs to look at that one
message's text -- no real multi-turn chat state to manage here, each call
is a fresh, stateless completion.
"""
import logging

import requests
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger("orchestrator")


class LiteRTServerUnavailable(RuntimeError):
    """Raised when the local Gemma model server can't be reached or errors
    out -- a genuine infrastructure failure, deliberately NOT swallowed
    into a fake "ERROR: ..." answer string (an earlier version of this
    file did that, which made a dead litert_server look like the model
    legitimately answered with an error message -- misleading, and it hid
    the failure from `api/query.py`'s error handling, which returns a
    proper `model_error` 500 for exactly this kind of thing instead)."""


class LiteRTGemmaChat(BaseChatModel):
    """Wraps `POST {server_url}/v1/chat` (see `litert_server/server.py`).
    `server_url` and `timeout` are plain pydantic fields (BaseChatModel is
    a pydantic model), so this can be constructed as
    `LiteRTGemmaChat(server_url=settings.litert_server_url)`."""

    server_url: str
    timeout: float = 180.0

    @property
    def _llm_type(self) -> str:
        return "litert-gemma"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs,
    ) -> ChatResult:
        # Only one message is ever expected here (see module docstring);
        # if more arrive, use the most recent one -- this backend has no
        # server-side conversation memory, everything must be in the text.
        prompt_text = messages[-1].content if messages else ""

        try:
            response = requests.post(
                f"{self.server_url}/v1/chat",
                json={"prompt": prompt_text},
                timeout=self.timeout,
            )
            response.raise_for_status()
            text = response.json()["text"]
        except requests.RequestException as e:
            logger.error("litert_server call failed: %s", e)
            raise LiteRTServerUnavailable(
                f"Could not reach the local Gemma model server at {self.server_url} ({e}). "
                "Is `litert_server/server.py` running? See orchestrator/README.md."
            ) from e

        # litert_lm has no native "stop sequence" concept (see
        # gemma_models/inference.py -- it just streams text until the
        # model itself stops), so the JSON-blob format's implicit stop
        # point is enforced here by truncating the raw text ourselves --
        # otherwise the model would happily keep hallucinating its own
        # fake Thought/Action/Observation turns past where it should have
        # stopped.
        if stop:
            for s in stop:
                idx = text.find(s)
                if idx != -1:
                    text = text[:idx]

        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])
