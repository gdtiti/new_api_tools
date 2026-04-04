"""
Temporary account API routes.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .auth import verify_auth
from .temporary_account_service import get_temporary_account_service

router = APIRouter(prefix="/api/temporary-accounts", tags=["Temporary Accounts"])


class TemporaryAccountResponse(BaseModel):
    success: bool
    message: str = ""
    data: dict


class CreateTemporaryAccountRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    remark: str = Field(default="", max_length=500)
    expires_at: int = Field(default=0, ge=0)
    quota: int = Field(default=0, ge=0)
    group_name: str = Field(default="default", max_length=64)
    token_name: str = Field(default="", max_length=128)
    email: Optional[str] = Field(default=None, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=128)


class UpdateTemporaryAccountStatusRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.get("", response_model=TemporaryAccountResponse)
def list_temporary_accounts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    _: str = Depends(verify_auth),
):
    data = get_temporary_account_service().list_accounts(page=page, page_size=page_size, status=status)
    return TemporaryAccountResponse(success=True, data=data)


@router.get("/capability", response_model=TemporaryAccountResponse)
def get_temporary_account_capability(_: str = Depends(verify_auth)):
    data = get_temporary_account_service().get_capability()
    return TemporaryAccountResponse(success=True, data=data)


@router.post("", response_model=TemporaryAccountResponse)
def create_temporary_account(
    request: CreateTemporaryAccountRequest,
    auth_type: str = Depends(verify_auth),
):
    operator = f"temporary-account:{auth_type}"
    result = get_temporary_account_service().create_account(
        username=request.username,
        remark=request.remark,
        created_by=operator,
        expires_at=request.expires_at,
        quota=request.quota,
        group_name=request.group_name,
        token_name=request.token_name,
        email=request.email,
        display_name=request.display_name,
    )
    return TemporaryAccountResponse(
        success=bool(result.get("success")),
        message=result.get("message") or "",
        data=result.get("data") or {"capability": result.get("capability")},
    )


@router.post("/{user_id}/disable", response_model=TemporaryAccountResponse)
def disable_temporary_account(
    user_id: int,
    request: UpdateTemporaryAccountStatusRequest,
    auth_type: str = Depends(verify_auth),
):
    operator = f"temporary-account:{auth_type}"
    result = get_temporary_account_service().disable_account(user_id=user_id, operator=operator, reason=request.reason)
    return TemporaryAccountResponse(
        success=bool(result.get("success")),
        message=result.get("message") or "",
        data={},
    )


@router.post("/{user_id}/enable", response_model=TemporaryAccountResponse)
def enable_temporary_account(
    user_id: int,
    request: UpdateTemporaryAccountStatusRequest,
    auth_type: str = Depends(verify_auth),
):
    operator = f"temporary-account:{auth_type}"
    result = get_temporary_account_service().enable_account(user_id=user_id, operator=operator, reason=request.reason)
    return TemporaryAccountResponse(
        success=bool(result.get("success")),
        message=result.get("message") or "",
        data={},
    )
