from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class UserProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    display_name: str = Field(min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    date_of_birth: date | None = None
    pronouns: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)
    locale: str = Field(default="en-US", min_length=2, max_length=40)
    bio: str | None = Field(default=None, max_length=4000)
    avatar_uri: str | None = Field(default=None, max_length=2000)


class WorldRoleGrant(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: uuid.UUID
    roles: frozenset[str] = frozenset()


class UserAccount(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: uuid.UUID
    actor_id: uuid.UUID
    username: str
    profile: UserProfile
    global_roles: frozenset[str] = frozenset()
    world_roles: tuple[WorldRoleGrant, ...] = ()
    password_change_required: bool = False
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime

    @property
    def is_admin(self) -> bool:
        return "ADMIN" in self.global_roles

    def roles_for(self, world_id: uuid.UUID) -> frozenset[str]:
        for grant in self.world_roles:
            if grant.world_id == world_id:
                return grant.roles
        return frozenset()

    @property
    def has_dm_role(self) -> bool:
        return any("DM" in grant.roles for grant in self.world_roles)

    @property
    def has_player_role(self) -> bool:
        return any("PLAYER" in grant.roles for grant in self.world_roles)


class AuthenticatedUser(UserAccount):
    session_id: uuid.UUID
    session_expires_at: datetime


@dataclass(frozen=True)
class CredentialRecord:
    account: UserAccount
    password_hash: str
    failed_login_count: int = 0
    locked_until: datetime | None = None
