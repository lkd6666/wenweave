from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class GroupMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    is_active: bool


class UserGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    members: list[GroupMemberRead] = Field(default_factory=list)
    created_at: datetime


class UserGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    user_ids: list[int] = Field(default_factory=list, max_length=500)


class UserGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    user_ids: list[int] | None = Field(default=None, max_length=500)
