"""
Subscription analytics API routes.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .auth import verify_auth
from .subscription_analytics_service import get_subscription_analytics_service

router = APIRouter(prefix="/api/subscription-analytics", tags=["Subscription Analytics"])


class SubscriptionAnalyticsResponse(BaseModel):
    success: bool
    data: dict


@router.get("/overview", response_model=SubscriptionAnalyticsResponse)
def get_subscription_analytics(_: str = Depends(verify_auth)):
    data = get_subscription_analytics_service().get_overview()
    return SubscriptionAnalyticsResponse(success=True, data=data)
