from __future__ import annotations

from .settings import Settings


def get_llm(settings: Settings | None = None):
    """Any LangChain chat model. Default Claude; set AGENT_MODEL='ollama:llama3.1' for local."""
    from langchain.chat_models import init_chat_model

    s = settings or Settings()
    return init_chat_model(s.model, temperature=0.2, max_retries=3, timeout=120)
