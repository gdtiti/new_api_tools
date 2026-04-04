"""
Channel insights API routes.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .auth import verify_auth
from .channel_insights_service import WINDOW_SECONDS, get_channel_insights_service
from .main import InvalidParamsError

router = APIRouter(prefix="/api/channel-insights", tags=["Channel Insights"])


class ChannelInsightsResponse(BaseModel):
    success: bool
    data: dict


def _validate_window(window: str) -> str:
    if window not in WINDOW_SECONDS:
        raise InvalidParamsError(message=f"Invalid window: {window}")
    return window


@router.get("/overview", response_model=ChannelInsightsResponse)
def get_channel_insights_overview(
    window: str = Query(default="24h", description="时间窗口 (1h/6h/24h/3d/7d/14d)"),
    limit: int = Query(default=20, ge=1, le=100, description="返回渠道数量"),
    no_cache: bool = Query(default=False, description="跳过缓存"),
    _: str = Depends(verify_auth),
):
    validated_window = _validate_window(window)
    data = get_channel_insights_service().get_overview(
        window=validated_window,
        limit=limit,
        use_cache=not no_cache,
    )
    return ChannelInsightsResponse(success=True, data=data)


@router.get("/{channel_id}", response_model=ChannelInsightsResponse)
def get_channel_insights_detail(
    channel_id: int,
    window: str = Query(default="24h", description="时间窗口 (1h/6h/24h/3d/7d/14d)"),
    no_cache: bool = Query(default=False, description="跳过缓存"),
    _: str = Depends(verify_auth),
):
    validated_window = _validate_window(window)
    data = get_channel_insights_service().get_channel_detail(
        channel_id=channel_id,
        window=validated_window,
        use_cache=not no_cache,
    )
    return ChannelInsightsResponse(success=True, data=data)


@router.post("/cache/invalidate", response_model=ChannelInsightsResponse)
def invalidate_channel_insights_cache(_: str = Depends(verify_auth)):
    deleted = get_channel_insights_service().invalidate_cache()
    return ChannelInsightsResponse(success=True, data={"deleted": deleted})
