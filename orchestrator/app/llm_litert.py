"""
app/llm_litert.py
===================
A LangChain `BaseChatModel` that talks to the small standalone
`litert_server` microservice (`orchestrator/litert_server/server.py`)
instead of loading the local Gemma model in-process -- see
`orchestrator/DESIGN.md` §3.1 for why that split exists.

How this gets used with a ReAct agent (`app/prompts.py` /
`app/llm_factory.py`): `create_react_agent` renders the ENTIRE prompt
(mission + tools + question + scratchpad-so-far) as one big string each
time it needs the next step, and LangChain auto-wraps a plain string into
a single `HumanMessage` before calling a chat model. So `_generate` below
only ever needs to look at that one message's text, no real multi-turn
chat state to manage -- each call is a fresh, stateless completion, which
matches how ReAct agents work with any plain completion-style model.
"""
import logging

import requests
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger("orchestrator")


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
        # The ReAct prompt template renders to one string, so there's
        # normally exactly one message here; if more ever arrive (e.g.
        # someone calls this model directly with real chat history), just
        # use the most recent one -- this backend has no notion of
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
            text = f"ERROR: local Gemma model server is unavailable ({e})"

        # litert_lm has no native "stop sequence" concept (see
        # gemma_models/inference.py -- it just streams text until the
        # model itself stops), so ReAct's "\nObservation" stop sequence is
        # enforced here by truncating the raw text ourselves -- otherwise
        # the model would happily keep "hallucinating" its own fake
        # Observation/Thought turns past where it should have stopped.
        if stop:
            for s in stop:
                idx = text.find(s)
                if idx != -1:
                    text = text[:idx]

        message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])
