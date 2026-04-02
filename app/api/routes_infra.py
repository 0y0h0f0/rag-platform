from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_provider_registry
from app.infra.provider_registry import ABTestingLLMProvider, ProviderRegistry

router = APIRouter(prefix="/infra", tags=["infra"])


class ModelInfo(BaseModel):
    provider: str
    model: str
    type: str
    role: str | None = None


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    results: dict[str, bool]


class ABConfigRequest(BaseModel):
    traffic_split: float = Field(ge=0.0, le=1.0)


class ABConfigResponse(BaseModel):
    traffic_split: float
    model_a: str
    model_b: str


class ABStatsResponse(BaseModel):
    stats: dict[str, dict]
    traffic_split: float


class ModelMetricsSummary(BaseModel):
    models: list[ModelInfo]
    health: dict[str, bool]


@router.get("/models", response_model=ModelsResponse)
def list_models(registry: ProviderRegistry = Depends(get_provider_registry)):
    models = registry.list_models()
    return ModelsResponse(models=[ModelInfo(**m) for m in models])


@router.get("/models/health", response_model=HealthResponse)
def models_health(registry: ProviderRegistry = Depends(get_provider_registry)):
    results = registry.health_check_all()
    # Update prometheus gauge
    from app.core.metrics import MODEL_HEALTH_STATUS
    for key, healthy in results.items():
        parts = key.split("/", 1)
        if len(parts) == 2:
            MODEL_HEALTH_STATUS.labels(provider=parts[0], model=parts[1]).set(1.0 if healthy else 0.0)
    return HealthResponse(results=results)


@router.post("/ab/config", response_model=ABConfigResponse)
def update_ab_config(
    payload: ABConfigRequest,
    registry: ProviderRegistry = Depends(get_provider_registry),
):
    llm = registry.get_llm()
    if not isinstance(llm, ABTestingLLMProvider):
        return ABConfigResponse(traffic_split=1.0, model_a="N/A", model_b="N/A")

    llm.split = payload.traffic_split
    return ABConfigResponse(
        traffic_split=llm.split,
        model_a=llm._provider_a.model_name,
        model_b=llm._provider_b.model_name,
    )


@router.get("/ab/stats", response_model=ABStatsResponse)
def ab_stats(registry: ProviderRegistry = Depends(get_provider_registry)):
    llm = registry.get_llm()
    if not isinstance(llm, ABTestingLLMProvider):
        return ABStatsResponse(stats={}, traffic_split=1.0)

    return ABStatsResponse(stats=llm.get_stats(), traffic_split=llm.split)


@router.get("/metrics/models", response_model=ModelMetricsSummary)
def model_metrics(registry: ProviderRegistry = Depends(get_provider_registry)):
    models = registry.list_models()
    health = registry.health_check_all()
    return ModelMetricsSummary(
        models=[ModelInfo(**m) for m in models],
        health=health,
    )
