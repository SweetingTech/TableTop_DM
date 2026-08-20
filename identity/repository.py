# ruff: noqa: E501 -- SQL statements retain one-to-one column/value alignment.
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg2.extras

from identity.models import CredentialRecord, UserAccount, UserProfile, WorldRoleGrant
from kernel.database import transaction

ADMIN_CAPABILITIES = frozenset(
    {
        "world.read",
        "world.read.all",
        "action.propose",
        "action.commit",
        "entity.create",
        "entity.control",
        "entity.read.secret",
        "faction.manage",
        "divine.invoke",
        "run.branch",
        "metric.evaluate",
        "canonical.promote",
        "mind.read.all",
        "mind.write.all",
    }
)
DM_CAPABILITIES = frozenset(
    {
        "world.read",
        "world.read.all",
        "action.propose",
        "action.commit",
        "entity.create",
        "entity.control",
        "entity.read.secret",
        "faction.manage",
        "divine.invoke",
        "run.branch",
        "mind.read.all",
        "mind.write.all",
    }
)
# A Player may speak and act at the table, but never controls an entity they were not
# explicitly granted, and never reads hidden state or branches a run.
PLAYER_CAPABILITIES = frozenset({"world.read", "action.propose", "action.commit"})
MANAGED_CAPABILITIES = ADMIN_CAPABILITIES | DM_CAPABILITIES | PLAYER_CAPABILITIES


def kernel_authority(
    *, is_admin: bool, world_roles: frozenset[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """Map product roles onto simulation actor roles and capabilities for one world.

    This is the single source of truth for the product-role -> capability translation that
    `AGENTS.md` requires to flow through explicit world grants. Both the durable
    (`sim.actor_capabilities`) and the in-process (`SimulationApplication.world_authorities`)
    authority stores are populated from it, so local and RLS authorization agree.
    """
    roles: set[str] = set()
    capabilities: set[str] = set()
    if is_admin:
        roles.add("ADMIN")
        capabilities |= ADMIN_CAPABILITIES
    if "DM" in world_roles:
        roles.add("GM")
        capabilities |= DM_CAPABILITIES
    if "PLAYER" in world_roles:
        roles.add("PLAYER")
        capabilities |= PLAYER_CAPABILITIES
    return frozenset(roles), frozenset(capabilities)


class IdentityRepository(Protocol):
    def ensure_bootstrap(self, password_hash: str) -> UserAccount: ...
    def get_credentials(self, username: str) -> CredentialRecord | None: ...
    def get_account(self, user_id: uuid.UUID) -> UserAccount | None: ...
    def list_accounts(self) -> tuple[UserAccount, ...]: ...
    def create_user(
        self, username: str, password_hash: str, profile: UserProfile, *, created_by: uuid.UUID
    ) -> UserAccount: ...
    def update_account(
        self,
        user_id: uuid.UUID,
        *,
        username: str | None = None,
        is_active: bool | None = None,
        profile: UserProfile | None = None,
        actor_user_id: uuid.UUID,
    ) -> UserAccount: ...
    def set_password(
        self,
        user_id: uuid.UUID,
        password_hash: str,
        *,
        require_change: bool,
        actor_user_id: uuid.UUID,
    ) -> None: ...
    def set_global_roles(
        self, user_id: uuid.UUID, roles: frozenset[str], *, actor_user_id: uuid.UUID
    ) -> UserAccount: ...
    def set_world_roles(
        self,
        user_id: uuid.UUID,
        world_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor_user_id: uuid.UUID,
    ) -> UserAccount: ...
    def create_session(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        *,
        user_agent: str | None,
        remote_address: str | None,
    ) -> tuple[uuid.UUID, datetime]: ...
    def account_for_session(
        self, token_hash: str
    ) -> tuple[UserAccount, uuid.UUID, datetime] | None: ...
    def revoke_session(self, token_hash: str) -> None: ...
    def revoke_user_sessions(self, user_id: uuid.UUID) -> None: ...
    def record_login_success(self, user_id: uuid.UUID) -> None: ...
    def record_login_failure(
        self, user_id: uuid.UUID, *, failed_login_count: int, locked_until: datetime | None
    ) -> None: ...
    def delete_user(self, user_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> None: ...
    def sync_admin_world(self, world_id: uuid.UUID) -> None: ...
    def audit_entries(self, limit: int = 100) -> tuple[dict[str, Any], ...]: ...


class InMemoryIdentityRepository:
    def __init__(self, *, bootstrap_actor_id: uuid.UUID | None = None) -> None:
        self._bootstrap_actor_id = bootstrap_actor_id
        self._credentials: dict[uuid.UUID, CredentialRecord] = {}
        self._usernames: dict[str, uuid.UUID] = {}
        self._sessions: dict[str, tuple[uuid.UUID, uuid.UUID, datetime, datetime | None]] = {}
        self._audit: list[dict[str, Any]] = []

    def ensure_bootstrap(self, password_hash: str) -> UserAccount:
        if self._credentials:
            return next(iter(self._credentials.values())).account
        now = datetime.now(UTC)
        account = UserAccount(
            user_id=uuid.uuid4(),
            actor_id=self._bootstrap_actor_id or uuid.uuid4(),
            username="admin",
            profile=UserProfile(display_name="Administrator"),
            global_roles=frozenset({"ADMIN"}),
            password_change_required=True,
            created_at=now,
        )
        self._credentials[account.user_id] = CredentialRecord(account, password_hash)
        self._usernames["admin"] = account.user_id
        self._record(None, account.user_id, "identity.bootstrap_admin")
        return account

    def get_credentials(self, username: str) -> CredentialRecord | None:
        identity = self._usernames.get(username.casefold())
        return self._credentials.get(identity) if identity else None

    def get_account(self, user_id: uuid.UUID) -> UserAccount | None:
        record = self._credentials.get(user_id)
        return record.account if record else None

    def list_accounts(self) -> tuple[UserAccount, ...]:
        return tuple(
            sorted(
                (row.account for row in self._credentials.values()),
                key=lambda row: row.username.casefold(),
            )
        )

    def create_user(
        self, username: str, password_hash: str, profile: UserProfile, *, created_by: uuid.UUID
    ) -> UserAccount:
        if username.casefold() in self._usernames:
            raise ValueError("username is already in use")
        now = datetime.now(UTC)
        account = UserAccount(
            user_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            username=username,
            profile=profile,
            password_change_required=True,
            created_at=now,
        )
        self._credentials[account.user_id] = CredentialRecord(account, password_hash)
        self._usernames[username.casefold()] = account.user_id
        self._record(created_by, account.user_id, "identity.user_created")
        return account

    def update_account(
        self,
        user_id: uuid.UUID,
        *,
        username: str | None = None,
        is_active: bool | None = None,
        profile: UserProfile | None = None,
        actor_user_id: uuid.UUID,
    ) -> UserAccount:
        record = self._required(user_id)
        values = record.account.model_dump()
        if username and username.casefold() != record.account.username.casefold():
            if username.casefold() in self._usernames:
                raise ValueError("username is already in use")
            del self._usernames[record.account.username.casefold()]
            self._usernames[username.casefold()] = user_id
            values["username"] = username
        if is_active is not None:
            values["is_active"] = is_active
        if profile is not None:
            values["profile"] = profile
        account = UserAccount.model_validate(values)
        self._credentials[user_id] = CredentialRecord(
            account, record.password_hash, record.failed_login_count, record.locked_until
        )
        self._record(actor_user_id, user_id, "identity.user_updated")
        return account

    def set_password(
        self,
        user_id: uuid.UUID,
        password_hash: str,
        *,
        require_change: bool,
        actor_user_id: uuid.UUID,
    ) -> None:
        record = self._required(user_id)
        account = record.account.model_copy(update={"password_change_required": require_change})
        self._credentials[user_id] = CredentialRecord(account, password_hash)
        self.revoke_user_sessions(user_id)
        self._record(
            actor_user_id,
            user_id,
            "identity.password_reset" if require_change else "identity.password_changed",
        )

    def set_global_roles(
        self, user_id: uuid.UUID, roles: frozenset[str], *, actor_user_id: uuid.UUID
    ) -> UserAccount:
        record = self._required(user_id)
        account = record.account.model_copy(update={"global_roles": roles})
        self._credentials[user_id] = CredentialRecord(
            account, record.password_hash, record.failed_login_count, record.locked_until
        )
        self._record(
            actor_user_id, user_id, "identity.global_roles_changed", {"roles": sorted(roles)}
        )
        return account

    def set_world_roles(
        self,
        user_id: uuid.UUID,
        world_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor_user_id: uuid.UUID,
    ) -> UserAccount:
        record = self._required(user_id)
        grants = {grant.world_id: grant.roles for grant in record.account.world_roles}
        if roles:
            grants[world_id] = roles
        else:
            grants.pop(world_id, None)
        world_roles = tuple(
            WorldRoleGrant(world_id=key, roles=value)
            for key, value in sorted(grants.items(), key=lambda item: str(item[0]))
        )
        account = record.account.model_copy(update={"world_roles": world_roles})
        self._credentials[user_id] = CredentialRecord(
            account, record.password_hash, record.failed_login_count, record.locked_until
        )
        self._record(
            actor_user_id,
            user_id,
            "identity.world_roles_changed",
            {"world_id": str(world_id), "roles": sorted(roles)},
        )
        return account

    def create_session(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        *,
        user_agent: str | None,
        remote_address: str | None,
    ) -> tuple[uuid.UUID, datetime]:
        session_id = uuid.uuid4()
        self._sessions[token_hash] = (session_id, user_id, expires_at, None)
        return session_id, expires_at

    def account_for_session(
        self, token_hash: str
    ) -> tuple[UserAccount, uuid.UUID, datetime] | None:
        session = self._sessions.get(token_hash)
        if session is None:
            return None
        session_id, user_id, expires_at, revoked_at = session
        if revoked_at is not None or expires_at <= datetime.now(UTC):
            return None
        account = self.get_account(user_id)
        if account is None or not account.is_active:
            return None
        return account, session_id, expires_at

    def revoke_session(self, token_hash: str) -> None:
        session = self._sessions.get(token_hash)
        if session:
            self._sessions[token_hash] = (*session[:3], datetime.now(UTC))

    def revoke_user_sessions(self, user_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        for key, session in tuple(self._sessions.items()):
            if session[1] == user_id:
                self._sessions[key] = (*session[:3], now)

    def record_login_success(self, user_id: uuid.UUID) -> None:
        record = self._required(user_id)
        account = record.account.model_copy(update={"last_login_at": datetime.now(UTC)})
        self._credentials[user_id] = CredentialRecord(account, record.password_hash)

    def record_login_failure(
        self, user_id: uuid.UUID, *, failed_login_count: int, locked_until: datetime | None
    ) -> None:
        record = self._required(user_id)
        self._credentials[user_id] = CredentialRecord(
            record.account, record.password_hash, failed_login_count, locked_until
        )

    def delete_user(self, user_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> None:
        record = self._required(user_id)
        self._record(
            actor_user_id, user_id, "identity.user_deleted", {"username": record.account.username}
        )
        self.revoke_user_sessions(user_id)
        del self._credentials[user_id]
        del self._usernames[record.account.username.casefold()]

    def sync_admin_world(self, world_id: uuid.UUID) -> None:
        return None

    def audit_entries(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        return tuple(reversed(self._audit[-limit:]))

    def _required(self, user_id: uuid.UUID) -> CredentialRecord:
        record = self._credentials.get(user_id)
        if record is None:
            raise KeyError(user_id)
        return record

    def _record(
        self,
        actor_user_id: uuid.UUID | None,
        target_user_id: uuid.UUID | None,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            {
                "actor_user_id": actor_user_id,
                "target_user_id": target_user_id,
                "event_type": event_type,
                "details": details or {},
                "occurred_at": datetime.now(UTC),
            }
        )


class PostgresIdentityRepository:
    def __init__(self, dsn: str, *, bootstrap_actor_id: uuid.UUID | None = None) -> None:
        self._dsn = dsn
        self._bootstrap_actor_id = bootstrap_actor_id

    def ensure_bootstrap(self, password_hash: str) -> UserAccount:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id FROM identity.users WHERE deleted_at IS NULL ORDER BY created_at LIMIT 1"
                )
                row = cursor.fetchone()
                if row is None:
                    actor_id = self._bootstrap_actor_id or uuid.uuid4()
                    user_id = uuid.uuid4()
                    cursor.execute(
                        """
                        INSERT INTO sim.actors(id, actor_kind, display_name, auth_subject)
                        VALUES (%s, 'HUMAN', 'Administrator', %s)
                        ON CONFLICT (id) DO UPDATE SET
                          display_name=EXCLUDED.display_name,
                          auth_subject=EXCLUDED.auth_subject,
                          is_active=true,
                          updated_at=now()
                        """,
                        (str(actor_id), f"user:{user_id}"),
                    )
                    cursor.execute(
                        """
                        INSERT INTO identity.users(id, actor_id, username, password_hash, password_change_required)
                        VALUES (%s, %s, 'admin', %s, true)
                        """,
                        (str(user_id), str(actor_id), password_hash),
                    )
                    cursor.execute(
                        "INSERT INTO identity.user_profiles(user_id, display_name) VALUES (%s, 'Administrator')",
                        (str(user_id),),
                    )
                    cursor.execute(
                        "INSERT INTO identity.global_roles(user_id, role) VALUES (%s, 'ADMIN')",
                        (str(user_id),),
                    )
                    cursor.execute(
                        "INSERT INTO identity.audit_log(target_user_id, event_type) VALUES (%s, 'identity.bootstrap_admin')",
                        (str(user_id),),
                    )
                    self._sync_authority(cursor, user_id, actor_id)
                    identity = user_id
                else:
                    identity = uuid.UUID(str(row["id"]))
        account = self.get_account(identity)
        if account is None:
            raise RuntimeError("bootstrap account could not be loaded")
        return account

    def get_credentials(self, username: str) -> CredentialRecord | None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id, password_hash, failed_login_count, locked_until FROM identity.users WHERE lower(username)=lower(%s) AND deleted_at IS NULL",
                    (username,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        account = self.get_account(uuid.UUID(str(row["id"])))
        if account is None:
            return None
        return CredentialRecord(
            account=account,
            password_hash=str(row["password_hash"]),
            failed_login_count=int(row["failed_login_count"]),
            locked_until=row["locked_until"],
        )

    def get_account(self, user_id: uuid.UUID) -> UserAccount | None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT u.*, p.display_name, p.legal_name, p.email, p.date_of_birth, p.pronouns,
                           p.timezone, p.locale, p.bio, p.avatar_uri
                    FROM identity.users u
                    JOIN identity.user_profiles p ON p.user_id = u.id
                    WHERE u.id = %s AND u.deleted_at IS NULL
                    """,
                    (str(user_id),),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    "SELECT role FROM identity.global_roles WHERE user_id=%s ORDER BY role",
                    (str(user_id),),
                )
                global_roles = frozenset(str(item["role"]) for item in cursor.fetchall())
                cursor.execute(
                    "SELECT world_id, role FROM identity.world_roles WHERE user_id=%s ORDER BY world_id, role",
                    (str(user_id),),
                )
                grouped: dict[uuid.UUID, set[str]] = defaultdict(set)
                for item in cursor.fetchall():
                    grouped[uuid.UUID(str(item["world_id"]))].add(str(item["role"]))
        return self._account(row, global_roles, grouped)

    def list_accounts(self) -> tuple[UserAccount, ...]:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM identity.users WHERE deleted_at IS NULL ORDER BY lower(username)"
                )
                identities = [uuid.UUID(str(row[0])) for row in cursor.fetchall()]
        return tuple(
            account
            for identity in identities
            if (account := self.get_account(identity)) is not None
        )

    def create_user(
        self, username: str, password_hash: str, profile: UserProfile, *, created_by: uuid.UUID
    ) -> UserAccount:
        actor_id = uuid.uuid4()
        user_id = uuid.uuid4()
        try:
            with transaction(dsn=self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO sim.actors(id, actor_kind, display_name, auth_subject) VALUES (%s, 'HUMAN', %s, %s)",
                        (str(actor_id), profile.display_name, f"user:{user_id}"),
                    )
                    cursor.execute(
                        """
                        INSERT INTO identity.users(id, actor_id, username, password_hash, password_change_required)
                        VALUES (%s, %s, %s, %s, true)
                        """,
                        (str(user_id), str(actor_id), username, password_hash),
                    )
                    self._save_profile(cursor, user_id, profile)
                    self._audit(cursor, created_by, user_id, "identity.user_created")
        except psycopg2.IntegrityError as exc:
            raise ValueError("username is already in use") from exc
        account = self.get_account(user_id)
        if account is None:
            raise RuntimeError("created user could not be loaded")
        return account

    def update_account(
        self,
        user_id: uuid.UUID,
        *,
        username: str | None = None,
        is_active: bool | None = None,
        profile: UserProfile | None = None,
        actor_user_id: uuid.UUID,
    ) -> UserAccount:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                if username is not None:
                    cursor.execute(
                        "UPDATE identity.users SET username=%s, updated_at=now() WHERE id=%s",
                        (username, str(user_id)),
                    )
                if is_active is not None:
                    cursor.execute(
                        "UPDATE identity.users SET is_active=%s, updated_at=now() WHERE id=%s",
                        (is_active, str(user_id)),
                    )
                    if not is_active:
                        cursor.execute(
                            "UPDATE identity.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                            (str(user_id),),
                        )
                if profile is not None:
                    self._save_profile(cursor, user_id, profile)
                    cursor.execute(
                        "UPDATE sim.actors SET display_name=%s, updated_at=now() WHERE id=(SELECT actor_id FROM identity.users WHERE id=%s)",
                        (profile.display_name, str(user_id)),
                    )
                self._audit(cursor, actor_user_id, user_id, "identity.user_updated")
        account = self.get_account(user_id)
        if account is None:
            raise KeyError(user_id)
        return account

    def set_password(
        self,
        user_id: uuid.UUID,
        password_hash: str,
        *,
        require_change: bool,
        actor_user_id: uuid.UUID,
    ) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE identity.users SET password_hash=%s, password_change_required=%s, failed_login_count=0, locked_until=NULL, updated_at=now() WHERE id=%s",
                    (password_hash, require_change, str(user_id)),
                )
                if cursor.rowcount != 1:
                    raise KeyError(user_id)
                cursor.execute(
                    "UPDATE identity.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                    (str(user_id),),
                )
                self._audit(
                    cursor,
                    actor_user_id,
                    user_id,
                    "identity.password_reset" if require_change else "identity.password_changed",
                )

    def set_global_roles(
        self, user_id: uuid.UUID, roles: frozenset[str], *, actor_user_id: uuid.UUID
    ) -> UserAccount:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM identity.global_roles WHERE user_id=%s", (str(user_id),)
                )
                for role in sorted(roles):
                    cursor.execute(
                        "INSERT INTO identity.global_roles(user_id, role, granted_by) VALUES (%s,%s,%s)",
                        (str(user_id), role, str(actor_user_id)),
                    )
                cursor.execute("SELECT actor_id FROM identity.users WHERE id=%s", (str(user_id),))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(user_id)
                self._sync_authority(cursor, user_id, uuid.UUID(str(row[0])))
                self._audit(
                    cursor,
                    actor_user_id,
                    user_id,
                    "identity.global_roles_changed",
                    {"roles": sorted(roles)},
                )
        account = self.get_account(user_id)
        if account is None:
            raise KeyError(user_id)
        return account

    def set_world_roles(
        self,
        user_id: uuid.UUID,
        world_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor_user_id: uuid.UUID,
    ) -> UserAccount:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM identity.world_roles WHERE user_id=%s AND world_id=%s",
                    (str(user_id), str(world_id)),
                )
                for role in sorted(roles):
                    cursor.execute(
                        "INSERT INTO identity.world_roles(world_id,user_id,role,granted_by) VALUES (%s,%s,%s,%s)",
                        (str(world_id), str(user_id), role, str(actor_user_id)),
                    )
                cursor.execute("SELECT actor_id FROM identity.users WHERE id=%s", (str(user_id),))
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(user_id)
                self._sync_authority(cursor, user_id, uuid.UUID(str(row[0])), world_id=world_id)
                self._audit(
                    cursor,
                    actor_user_id,
                    user_id,
                    "identity.world_roles_changed",
                    {"world_id": str(world_id), "roles": sorted(roles)},
                )
        account = self.get_account(user_id)
        if account is None:
            raise KeyError(user_id)
        return account

    def create_session(
        self,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        *,
        user_agent: str | None,
        remote_address: str | None,
    ) -> tuple[uuid.UUID, datetime]:
        session_id = uuid.uuid4()
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO identity.sessions(id,user_id,token_hash,user_agent,remote_address,expires_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        str(session_id),
                        str(user_id),
                        token_hash,
                        user_agent,
                        remote_address,
                        expires_at,
                    ),
                )
        return session_id, expires_at

    def account_for_session(
        self, token_hash: str
    ) -> tuple[UserAccount, uuid.UUID, datetime] | None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE identity.sessions s SET last_seen_at=now()
                    FROM identity.users u
                    WHERE s.token_hash=%s AND s.user_id=u.id AND s.revoked_at IS NULL
                      AND s.expires_at>now() AND u.is_active AND u.deleted_at IS NULL
                    RETURNING s.user_id, s.id, s.expires_at
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        account = self.get_account(uuid.UUID(str(row["user_id"])))
        return (account, uuid.UUID(str(row["id"])), row["expires_at"]) if account else None

    def revoke_session(self, token_hash: str) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE identity.sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL",
                    (token_hash,),
                )

    def revoke_user_sessions(self, user_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE identity.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                    (str(user_id),),
                )

    def record_login_success(self, user_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE identity.users SET failed_login_count=0, locked_until=NULL, last_login_at=now(), updated_at=now() WHERE id=%s",
                    (str(user_id),),
                )

    def record_login_failure(
        self, user_id: uuid.UUID, *, failed_login_count: int, locked_until: datetime | None
    ) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE identity.users SET failed_login_count=%s, locked_until=%s, updated_at=now() WHERE id=%s",
                    (failed_login_count, locked_until, str(user_id)),
                )

    def delete_user(self, user_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT username, actor_id FROM identity.users WHERE id=%s", (str(user_id),)
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(user_id)
                self._audit(
                    cursor, actor_user_id, user_id, "identity.user_deleted", {"username": row[0]}
                )
                cursor.execute(
                    "UPDATE identity.sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
                    (str(user_id),),
                )
                cursor.execute(
                    "DELETE FROM identity.global_roles WHERE user_id=%s", (str(user_id),)
                )
                cursor.execute("DELETE FROM identity.world_roles WHERE user_id=%s", (str(user_id),))
                cursor.execute(
                    """
                    UPDATE identity.user_profiles
                    SET display_name='Deleted user', legal_name=NULL, email=NULL,
                        date_of_birth=NULL, pronouns=NULL, bio=NULL, avatar_uri=NULL, updated_at=now()
                    WHERE user_id=%s
                    """,
                    (str(user_id),),
                )
                cursor.execute(
                    "UPDATE identity.users SET username=%s, is_active=false, deleted_at=now(), updated_at=now() WHERE id=%s",
                    (f"deleted-{user_id}", str(user_id)),
                )
                cursor.execute(
                    "UPDATE sim.actors SET is_active=false, updated_at=now() WHERE id=%s",
                    (str(row[1]),),
                )

    def sync_admin_world(self, world_id: uuid.UUID) -> None:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT u.id, u.actor_id FROM identity.users u JOIN identity.global_roles r ON r.user_id=u.id WHERE r.role='ADMIN' AND u.deleted_at IS NULL"
                )
                for user_id, actor_id in cursor.fetchall():
                    self._sync_authority(
                        cursor, uuid.UUID(str(user_id)), uuid.UUID(str(actor_id)), world_id=world_id
                    )

    def audit_entries(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        with transaction(dsn=self._dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM identity.audit_log ORDER BY id DESC LIMIT %s", (limit,)
                )
                return tuple(dict(row) for row in cursor.fetchall())

    @staticmethod
    def _account(
        row: dict[str, Any], global_roles: frozenset[str], grouped: dict[uuid.UUID, set[str]]
    ) -> UserAccount:
        return UserAccount(
            user_id=uuid.UUID(str(row["id"])),
            actor_id=uuid.UUID(str(row["actor_id"])),
            username=str(row["username"]),
            profile=UserProfile(
                display_name=str(row["display_name"]),
                legal_name=row["legal_name"],
                email=row["email"],
                date_of_birth=row["date_of_birth"],
                pronouns=row["pronouns"],
                timezone=str(row["timezone"]),
                locale=str(row["locale"]),
                bio=row["bio"],
                avatar_uri=row["avatar_uri"],
            ),
            global_roles=global_roles,
            world_roles=tuple(
                WorldRoleGrant(world_id=world_id, roles=frozenset(roles))
                for world_id, roles in sorted(grouped.items(), key=lambda item: str(item[0]))
            ),
            password_change_required=bool(row["password_change_required"]),
            is_active=bool(row["is_active"]),
            last_login_at=row["last_login_at"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _save_profile(cursor, user_id: uuid.UUID, profile: UserProfile) -> None:
        cursor.execute(
            """
            INSERT INTO identity.user_profiles(user_id,display_name,legal_name,email,date_of_birth,pronouns,timezone,locale,bio,avatar_uri)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET display_name=excluded.display_name,
              legal_name=excluded.legal_name,email=excluded.email,date_of_birth=excluded.date_of_birth,
              pronouns=excluded.pronouns,timezone=excluded.timezone,locale=excluded.locale,
              bio=excluded.bio,avatar_uri=excluded.avatar_uri,updated_at=now()
            """,
            (
                str(user_id),
                profile.display_name,
                profile.legal_name,
                profile.email,
                profile.date_of_birth,
                profile.pronouns,
                profile.timezone,
                profile.locale,
                profile.bio,
                profile.avatar_uri,
            ),
        )

    @staticmethod
    def _audit(
        cursor,
        actor_user_id: uuid.UUID | None,
        target_user_id: uuid.UUID | None,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        cursor.execute(
            "INSERT INTO identity.audit_log(actor_user_id,target_user_id,event_type,details) VALUES (%s,%s,%s,%s::jsonb)",
            (
                str(actor_user_id) if actor_user_id else None,
                str(target_user_id) if target_user_id else None,
                event_type,
                psycopg2.extras.Json(details or {}),
            ),
        )

    @staticmethod
    def _sync_authority(
        cursor, user_id: uuid.UUID, actor_id: uuid.UUID, *, world_id: uuid.UUID | None = None
    ) -> None:
        def value(row: Any, column: str) -> Any:
            return row[column] if isinstance(row, dict) else row[0]

        world_clause = "WHERE id=%s" if world_id else ""
        parameters = (str(world_id),) if world_id else ()
        cursor.execute(f"SELECT id FROM sim.worlds {world_clause} ORDER BY id", parameters)
        worlds = [uuid.UUID(str(value(row, "id"))) for row in cursor.fetchall()]
        cursor.execute("SELECT role FROM identity.global_roles WHERE user_id=%s", (str(user_id),))
        is_admin = any(value(row, "role") == "ADMIN" for row in cursor.fetchall())
        for current_world in worlds:
            cursor.execute(
                "SELECT role FROM identity.world_roles WHERE user_id=%s AND world_id=%s",
                (str(user_id), str(current_world)),
            )
            identity_roles = frozenset(str(value(row, "role")) for row in cursor.fetchall())
            actor_roles, capabilities = kernel_authority(
                is_admin=is_admin, world_roles=identity_roles
            )
            cursor.execute(
                "DELETE FROM sim.actor_roles WHERE world_id=%s AND actor_id=%s AND role IN ('ADMIN','GM','PLAYER')",
                (str(current_world), str(actor_id)),
            )
            cursor.execute(
                "DELETE FROM sim.actor_capabilities WHERE world_id=%s AND actor_id=%s AND capability = ANY(%s)",
                (str(current_world), str(actor_id), list(MANAGED_CAPABILITIES)),
            )
            for role in sorted(actor_roles):
                cursor.execute(
                    "INSERT INTO sim.actor_roles(world_id,actor_id,role) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (str(current_world), str(actor_id), role),
                )
            for capability in sorted(capabilities):
                cursor.execute(
                    "INSERT INTO sim.actor_capabilities(world_id,actor_id,capability) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (str(current_world), str(actor_id), capability),
                )
