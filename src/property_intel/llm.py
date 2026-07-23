from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_xai import ChatXAI
from pydantic import BaseModel

from property_intel.config import Settings, get_settings

SchemaT = TypeVar("SchemaT", bound=BaseModel)

# json_mode (OpenAI-compatible gateways e.g. 9Router → Groq) requires "json" in messages.
JSON_MODE_SYSTEM_SUFFIX = "\n\nRespond with a valid JSON object matching the schema."


def uses_openai_gateway(settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return cfg.llm_provider == "openai" and bool(cfg.openai_api_base.strip())


def augment_system_prompt_for_structured(system_prompt: str, settings: Settings | None = None) -> str:
    if uses_openai_gateway(settings):
        return system_prompt + JSON_MODE_SYSTEM_SUFFIX
    return system_prompt


def with_structured_output_compat(
    llm: BaseChatModel,
    schema: type[SchemaT],
    settings: Settings | None = None,
) -> Runnable:
    """Structured output tuned per provider (9Router/Groq reject json_schema)."""
    cfg = settings or get_settings()
    if uses_openai_gateway(cfg):
        return llm.with_structured_output(schema, method="json_mode")
    if cfg.llm_provider == "groq":
        return llm.with_structured_output(schema, method="function_calling")
    return llm.with_structured_output(schema)


def get_chat_model(settings: Settings | None = None) -> BaseChatModel:
    cfg = settings or get_settings()
    provider = cfg.llm_provider

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=cfg.gemini_model,
            google_api_key=cfg.google_api_key,
            temperature=0,
        )
    if provider == "grok":
        return ChatXAI(
            model=cfg.grok_model,
            xai_api_key=cfg.xai_api_key,
            temperature=0,
        )
    if provider == "groq":
        return ChatGroq(
            model=cfg.groq_model,
            groq_api_key=cfg.groq_api_key,
            temperature=0,
        )
    api_key = cfg.openai_api_key.strip() or "local-gateway"
    kwargs: dict = {
        "model": cfg.openai_model,
        "api_key": api_key,
        "temperature": 0,
    }
    if cfg.openai_api_base.strip():
        kwargs["base_url"] = cfg.openai_api_base.rstrip("/")
    return ChatOpenAI(**kwargs)
