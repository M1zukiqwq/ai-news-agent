from .base import BaseCollector
from .openai_collector import OpenAICollector
from .google_collector import GoogleCollector
from .anthropic_collector import AnthropicCollector
from .meta_collector import MetaCollector
from .huggingface_collector import HuggingFaceCollector
from .general_news_collector import GeneralNewsCollector
from .china_ai_collector import ChinaAICollector
from .web_search_collector import WebSearchCollector

COLLECTOR_MAP = {
    "openai": OpenAICollector,
    "google": GoogleCollector,
    "anthropic": AnthropicCollector,
    "meta": MetaCollector,
    "huggingface": HuggingFaceCollector,
    "general_news": GeneralNewsCollector,
    "china_ai": ChinaAICollector,
    "web_search": WebSearchCollector,
}

__all__ = [
    "BaseCollector",
    "OpenAICollector",
    "GoogleCollector",
    "AnthropicCollector",
    "MetaCollector",
    "HuggingFaceCollector",
    "GeneralNewsCollector",
    "ChinaAICollector",
    "WebSearchCollector",
    "COLLECTOR_MAP",
]
