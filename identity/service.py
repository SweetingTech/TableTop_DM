from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from identity.models import AuthenticatedUser, UserAccount, UserProfile
from identity.passwords import hash_password, validate_password, verify_password
from identity.repository import IdentityRepository

USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
SESSION_TTL = timedelta(hours=12)
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION = timedelta(minutes=15)


class AuthenticationError(PermissionError):
    pass


class IdentityService:
    def __init__(self, repository: IdentityRepository) -> None:
        self.repository = repository
        self._dummy_hash = hash_password(secrets.token_urlsafe(24))
        self.bootstrap_admin = repository.ensure_bootstrap(
            hash_password("admin123", allow_bootstrap_default=True)
        )

    def login(
        self,
        username: str,
        password: str,
        *,
        user_agent: str | None = None,
        remote_address: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        record = self.repository.get_credentials(username.strip())
        encoded = record.password_hash if record else self._dummy_hash
        valid = verify_password(password, encoded)
        now = datetime.now(UTC)
        if record is None or not valid:
            if record is not None:
                failed = record.failed_login_count + 1
                locked_until = now + LOCKOUT_DURATION if failed >= LOCKOUT_THRESHOLD else None
                self.repository.record_login_failure(
                    record.account.user_id, locked_until=locked_until
                )
            raise AuthenticationError("invalid username or password")
        if not record.account.is_active:
            raise AuthenticationError("account is disabled")
        if record.locked_until and record.locked_until > now:
            raise AuthenticationError("account is temporarily locked")
        self.repository.record_login_success(record.account.user_id)
        return self._new_session(
            record.account.user_id,
            user_agent=user_agent,
            remote_address=remote_address,
        )

    def authenticate(self, token: str | None) -> AuthenticatedUser | None:
        if not token:
            return None
        result = self.repository.account_for_session(self._token_hash(token))
        if result is None:
            return None
        account, session_id, expires_at = result
        return AuthenticatedUser(
            **account.model_dump(),
            session_id=session_id,
            session_expires_at=expires_at,
        )

    def logout(self, token: str | None) -> None:
        if token:
            self.repository.revoke_session(self._token_hash(token))

    def change_password(
        self,
        user: AuthenticatedUser,
        current_password: str,
        new_password: str,
        *,
        user_agent: str | None = None,
        remote_address: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        record = self.repository.get_credentials(user.username)
        if record is None or not verify_password(current_password, record.password_hash):
            raise AuthenticationError("current password is incorrect")
        if verify_password(new_password, record.password_hash):
            raise ValueError("new password must be different from the current password")
        validate_password(new_password)
        self.repository.set_password(
            user.user_id,
            hash_password(new_password),
            require_change=False,
            actor_user_id=user.user_id,
        )
        return self._new_session(
            user.user_id,
            user_agent=user_agent,
            remote_address=remote_address,
        )

    def update_profile(self, user: AuthenticatedUser, profile: UserProfile) -> UserAccount:
        return self.repository.update_account(
            user.user_id,
            profile=profile,
            actor_user_id=user.user_id,
        )

    def list_users(self, actor: AuthenticatedUser) -> tuple[UserAccount, ...]:
        self.require_admin(actor)
        return self.repository.list_accounts()

    def create_user(
        self,
        actor: AuthenticatedUser,
        *,
        username: str,
        temporary_password: str,
        profile: UserProfile,
    ) -> UserAccount:
        self.require_admin(actor)
        self._validate_username(username)
        validate_password(temporary_password)
        return self.repository.create_user(
            username.strip(),
            hash_password(temporary_password),
            profile,
            created_by=actor.user_id,
        )

    def update_user(
        self,
        actor: AuthenticatedUser,
        user_id: uuid.UUID,
        *,
        username: str | None = None,
        is_active: bool | None = None,
        profile: UserProfile | None = None,
    ) -> UserAccount:
        self.require_admin(actor)
        if username is not None:
            self._validate_username(username)
        if user_id == actor.user_id and is_active is False:
            raise ValueError("you cannot disable your own account")
        return self.repository.update_account(
            user_id,
            username=username.strip() if username else None,
            is_active=is_active,
            profile=profile,
            actor_user_id=actor.user_id,
        )

    def reset_password(
        self,
        actor: AuthenticatedUser,
        user_id: uuid.UUID,
        temporary_password: str,
    ) -> None:
        self.require_admin(actor)
        validate_password(temporary_password)
        self.repository.set_password(
            user_id,
            hash_password(temporary_password),
            require_change=True,
            actor_user_id=actor.user_id,
        )

    def set_global_roles(
        self,
        actor: AuthenticatedUser,
        user_id: uuid.UUID,
        roles: frozenset[str],
    ) -> UserAccount:
        self.require_admin(actor)
        if roles - {"ADMIN"}:
            raise ValueError("unsupported global role")
        existing = self.repository.get_account(user_id)
        if existing is None:
            raise KeyError(user_id)
        if existing.is_admin and "ADMIN" not in roles and self._admin_count() <= 1:
            raise ValueError("the final administrator role cannot be removed")
        return self.repository.set_global_roles(
            user_id,
            roles,
            actor_user_id=actor.user_id,
        )

    def set_world_roles(
        self,
        actor: AuthenticatedUser,
        user_id: uuid.UUID,
        world_id: uuid.UUID,
        roles: frozenset[str],
    ) -> UserAccount:
        self.require_admin(actor)
        if roles - {"DM", "PLAYER"}:
            raise ValueError("world roles must be DM, PLAYER, or both")
        return self.repository.set_world_roles(
            user_id,
            world_id,
            roles,
            actor_user_id=actor.user_id,
        )

    def delete_user(self, actor: AuthenticatedUser, user_id: uuid.UUID) -> None:
        self.require_admin(actor)
        if user_id == actor.user_id:
            raise ValueError("you cannot delete your own account")
        target = self.repository.get_account(user_id)
        if target is None:
            raise KeyError(user_id)
        if target.is_admin and self._admin_count() <= 1:
            raise ValueError("the final administrator account cannot be deleted")
        self.repository.delete_user(user_id, actor_user_id=actor.user_id)

    def sync_admin_world(self, world_id: uuid.UUID) -> None:
        self.repository.sync_admin_world(world_id)

    @staticmethod
    def require_admin(user: UserAccount) -> None:
        if not user.is_admin:
            raise PermissionError("administrator role required")

    @staticmethod
    def require_world_role(user: UserAccount, world_id: uuid.UUID, *roles: str) -> None:
        if user.is_admin:
            return
        if not user.roles_for(world_id).intersection(roles):
            raise PermissionError(f"one of these world roles is required: {', '.join(roles)}")

    def _new_session(
        self,
        user_id: uuid.UUID,
        *,
        user_agent: str | None,
        remote_address: str | None,
    ) -> tuple[AuthenticatedUser, str]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + SESSION_TTL
        session_id, expires_at = self.repository.create_session(
            user_id,
            self._token_hash(token),
            expires_at,
            user_agent=user_agent,
            remote_address=remote_address,
        )
        account = self.repository.get_account(user_id)
        if account is None:
            raise AuthenticationError("account no longer exists")
        return (
            AuthenticatedUser(
                **account.model_dump(),
                session_id=session_id,
                session_expires_at=expires_at,
            ),
            token,
        )

    def _admin_count(self) -> int:
        return sum(account.is_admin for account in self.repository.list_accounts())

    @staticmethod
    def _validate_username(username: str) -> None:
        if not USERNAME.fullmatch(username.strip()):
            raise ValueError(
                "username must be 3-64 characters using letters, numbers, dot, dash, or underscore"
            )

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
