from app.core.config import settings
from app.infra.provider_registry import ProviderRegistry
from app.services.llm_service import LLMService


def test_llm_service_requires_api_key() -> None:
    original_provider = settings.llm_provider
    original_api_key = settings.llm_api_key
    original_instance = ProviderRegistry._instance

    settings.llm_provider = "deepseek"
    settings.llm_api_key = ""
    # Reset singleton so it picks up the new provider setting
    ProviderRegistry._instance = None

    try:
        answer = LLMService().answer(
            "这个系统为什么要异步化？",
            [{"source": "demo", "chunk_index": 0, "text": "异步任务可以解耦上传与索引构建。"}],
        )
        assert "API Key" in answer
    finally:
        settings.llm_provider = original_provider
        settings.llm_api_key = original_api_key
        ProviderRegistry._instance = original_instance
