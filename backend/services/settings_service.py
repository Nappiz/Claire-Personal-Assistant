"""Compatibility functions; SQLAlchemy persistence belongs to the repository."""
from app.infrastructure.persistence.settings import SQLAlchemySettingsRepository

def get_setting(db, key: str, default_value=None):
    return SQLAlchemySettingsRepository(db).get(key, default_value)

def set_setting(db, key: str, value):
    return SQLAlchemySettingsRepository(db).set(key, value)
