"""
Config Router — CRUD for Snowsky settings.
"""
from fastapi import APIRouter

from backend.models import ConfigResponse, ConfigUpdate
from backend.services import config as config_svc

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigResponse)
async def get_config():
    """Get current configuration."""
    cfg = config_svc.load_config()
    return ConfigResponse(**cfg)


@router.patch("", response_model=ConfigResponse)
async def update_config(updates: ConfigUpdate):
    """Apply partial config updates."""
    # Filter out None values to only update provided fields
    update_dict = {k: v for k, v in updates.model_dump().items() if v is not None}
    cfg = config_svc.update_config(update_dict)
    return ConfigResponse(**cfg)


@router.get("/path")
async def get_config_path():
    """Get the config file path (for debugging)."""
    return {"path": config_svc.get_config_path()}
