from typing import Literal

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)


class MembershipInfo(BaseModel):
    is_vip: bool
    source: Literal["one_time", "subscription"] | None = None
    expires_at: str | None = None
    subscription_status: str | None = None
    cancel_at_period_end: bool = False


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    csrf_token: str
    membership: MembershipInfo
    remaining_free_downloads: int | None


class AuthResponse(CurrentUserResponse):
    pass


class SupportRequest(BaseModel):
    subject: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=10, max_length=4000)


class SupportResponse(BaseModel):
    id: str
    status: str

