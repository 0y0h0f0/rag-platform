from app.services.cache_service import CacheService


def test_cache_key_is_deterministic() -> None:
    service = CacheService()
    payload = {"query": "hello", "top_k": 5}
    key_1 = service._key("search", payload)
    key_2 = service._key("search", payload)
    assert key_1 == key_2

