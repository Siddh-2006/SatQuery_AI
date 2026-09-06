"""
app/llm_gemini.py
===================
Builds the Gemini-backed chat model, using `langchain-google-genai`'s
`ChatGoogleGenerativeAI` -- which supports real, native tool/function
calling (`.bind_tools()`), unlike the local LiteRT-Gemma path (see
`orchestrator/DESIGN.md` §3.3). This is the whole file -- there's no
custom wrapper needed here, just consistent construction from settings.
"""
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def build_gemini_chat_model() -> ChatGoogleGenerativeAI:
    if not settings.gemini_api_key:
        raise RuntimeError(
            "LLM_BACKEND=gemini but GEMINI_API_KEY is not set. "
            "Set it in your .env (see orchestrator/.env.example)."
        )
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.2,  # low but not zero -- keeps template-shaped instructions consistent
    )
