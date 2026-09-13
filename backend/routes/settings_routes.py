from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from configs.database import get_db
from services import settings_service
from pydantic import BaseModel
from typing import Any

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
def reveal_api_keys(response: Response, db: Session = Depends(get_db)):
    """Return persisted API keys for the local settings form without caching them."""
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    value = settings_service.get_setting(db, "api_keys")
    return {"key": "api_keys", "value": value if isinstance(value, dict) else {}}


@router.get("/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_db)):
    value = settings_service.get_setting(db, key)
    return {"key": key, "value": _safe_setting_value(key, value)}

@router.post("/settings")
def set_setting(data: SettingUpdate, db: Session = Depends(get_db)):
    value = settings_service.set_setting(db, data.key, data.value)
    return {"key": data.key, "value": _safe_setting_value(data.key, value)}

@router.post("/settings/memory/consolidate")
def consolidate_memory(days_passed: float = Query(1.0, gt=0, le=30)):
    from services.neo4j_service import neo4j_client
    stats = neo4j_client.consolidate_memory(days_passed=days_passed)
    return {"message": f"Memory consolidation finished (decayed {days_passed} days)", "stats": stats}
