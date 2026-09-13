from typing import Any
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from app.api.dependencies import get_db, resource_dependencies
from app.application.settings import operations

router = APIRouter()
_SENSITIVE_SETTINGS = {"api_keys"}


def _safe_setting_value(key: str, value):
    """Return configuration state without ever serializing provider secrets."""
    if key not in _SENSITIVE_SETTINGS:
        return value
    if isinstance(value, dict):
        return {provider: {"configured": bool(secret)} for provider, secret in value.items()}
    return {"configured": bool(value)}


class SettingUpdate(BaseModel):
    key: str
    value: Any


@router.get("/settings/api_keys/reveal")
def reveal_api_keys(response: Response, db: Any = Depends(get_db)):
    """Return persisted API keys for the local settings form without caching them."""
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    value = operations.get_setting("api_keys", resource_dependencies(db))
    return {"key": "api_keys", "value": value if isinstance(value, dict) else {}}


@router.get("/settings/{key}")
def get_setting(key: str, db: Any = Depends(get_db)):
    value = operations.get_setting(key, resource_dependencies(db))
    return {"key": key, "value": _safe_setting_value(key, value)}


@router.post("/settings")
def set_setting(data: SettingUpdate, db: Any = Depends(get_db)):
    value = operations.set_setting(data.key, data.value, resource_dependencies(db))
    return {"key": data.key, "value": _safe_setting_value(data.key, value)}


@router.post("/settings/memory/consolidate")
def consolidate_memory(days_passed: float = Query(1.0, gt=0, le=30)):
    return operations.consolidate_memory(days_passed, resource_dependencies())
