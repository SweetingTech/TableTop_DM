import uuid

import pytest

from identity.models import UserProfile
from identity.repository import InMemoryIdentityRepository
from identity.service import AuthenticationError, IdentityService


def test_bootstrap_login_requires_password_change_and_rotates_session() -> None:
    repository = InMemoryIdentityRepository()
    service = IdentityService(repository)

    administrator, initial_token = service.login("admin", "admin123")
    assert administrator.is_admin
    assert administrator.password_change_required
    assert service.authenticate(initial_token) is not None

    changed, changed_token = service.change_password(
        administrator, "admin123", "Private-Administrator-2026!"
    )
    assert not changed.password_change_required
    assert service.authenticate(initial_token) is None
    assert service.authenticate(changed_token) is not None
    with pytest.raises(AuthenticationError):
        service.login("admin", "admin123")


def test_admin_manages_accounts_and_world_scoped_roles() -> None:
    service = IdentityService(InMemoryIdentityRepository())
    administrator, _ = service.login("admin", "admin123")
    world_id = uuid.uuid4()
    player = service.create_user(
        administrator,
        username="rowan",
        temporary_password="Temporary-Player-2026!",
        profile=UserProfile(display_name="Rowan", pronouns="they/them"),
    )
    assigned = service.set_world_roles(
        administrator, player.user_id, world_id, frozenset({"DM", "PLAYER"})
    )
    assert assigned.roles_for(world_id) == frozenset({"DM", "PLAYER"})
    service.reset_password(administrator, player.user_id, "Replacement-Player-2026!")
    signed_in, _ = service.login("rowan", "Replacement-Player-2026!")
    assert signed_in.password_change_required

    service.delete_user(administrator, player.user_id)
    assert all(account.user_id != player.user_id for account in service.list_users(administrator))


def test_last_administrator_cannot_remove_or_delete_itself() -> None:
    service = IdentityService(InMemoryIdentityRepository())
    administrator, _ = service.login("admin", "admin123")
    with pytest.raises(ValueError, match="final administrator"):
        service.set_global_roles(administrator, administrator.user_id, frozenset())
    with pytest.raises(ValueError, match="own account"):
        service.delete_user(administrator, administrator.user_id)


def test_disabled_administrators_do_not_satisfy_the_final_administrator_guard() -> None:
    """A disabled administrator cannot administer anything, so it cannot be the last one."""
    service = IdentityService(InMemoryIdentityRepository())
    administrator, _ = service.login("admin", "admin123")
    understudy = service.create_user(
        administrator,
        username="understudy",
        temporary_password="Temporary-Second-2026!",
        profile=UserProfile(display_name="Understudy"),
    )
    service.set_global_roles(administrator, understudy.user_id, frozenset({"ADMIN"}))

    service.update_user(administrator, understudy.user_id, is_active=False)

    # The disabled understudy no longer counts, so the live administrator is now the last one.
    with pytest.raises(ValueError, match="final administrator"):
        service.set_global_roles(administrator, administrator.user_id, frozenset())

    # Removing the disabled account itself is still fine: a live administrator remains.
    service.delete_user(administrator, understudy.user_id)
    understudy = service.create_user(
        administrator,
        username="understudy2",
        temporary_password="Temporary-Third-2026!",
        profile=UserProfile(display_name="Understudy"),
    )
    service.set_global_roles(administrator, understudy.user_id, frozenset({"ADMIN"}))
    stood_down = service.set_global_roles(administrator, administrator.user_id, frozenset())
    assert not stood_down.is_admin


def test_the_last_active_administrator_cannot_be_disabled() -> None:
    service = IdentityService(InMemoryIdentityRepository())
    administrator, _ = service.login("admin", "admin123")
    deputy = service.create_user(
        administrator,
        username="deputy",
        temporary_password="Temporary-Deputy-2026!",
        profile=UserProfile(display_name="Deputy"),
    )
    service.set_global_roles(administrator, deputy.user_id, frozenset({"ADMIN"}))
    deputy_session, _ = service.login("deputy", "Temporary-Deputy-2026!")

    service.update_user(deputy_session, administrator.user_id, is_active=False)
    with pytest.raises(ValueError, match="own account"):
        service.update_user(deputy_session, deputy_session.user_id, is_active=False)
