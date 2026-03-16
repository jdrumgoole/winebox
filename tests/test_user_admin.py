"""Tests for the user administration CLI functions."""

import uuid

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from winebox.cli.user_admin import (
    add_user,
    change_password,
    disable_user,
    enable_user,
    list_users,
    remove_user,
    verify_user,
)
from winebox.models.user import User
from winebox.services.auth import get_password_hash, verify_password


@pytest_asyncio.fixture
async def admin_user(init_test_db):
    """Create an admin user."""
    now = datetime.now(timezone.utc)
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        hashed_password=get_password_hash("adminpass"),
        is_superuser=True,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )
    await user.insert()
    return user


@pytest_asyncio.fixture
async def regular_user(init_test_db):
    """Create a regular user."""
    now = datetime.now(timezone.utc)
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        hashed_password=get_password_hash("userpass"),
        is_superuser=False,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )
    await user.insert()
    return user


class TestAddUser:
    """Tests for add_user."""

    @pytest.mark.asyncio
    async def test_add_user_success(self, init_test_db, capsys):
        unique_email = f"new-{uuid.uuid4().hex[:8]}@example.com"
        await add_user(unique_email, "password123", skip_db_init=True)
        output = capsys.readouterr().out
        assert "created successfully" in output

        user = await User.find_one(User.email == unique_email)
        assert user is not None
        assert user.is_active is True
        assert user.is_verified is True
        assert user.is_superuser is False

    @pytest.mark.asyncio
    async def test_add_admin_user(self, init_test_db, capsys):
        unique_email = f"admin2-{uuid.uuid4().hex[:8]}@example.com"
        await add_user(unique_email, "password123", is_admin=True, skip_db_init=True)
        output = capsys.readouterr().out
        assert "admin" in output

        user = await User.find_one(User.email == unique_email)
        assert user.is_superuser is True

    @pytest.mark.asyncio
    async def test_add_duplicate_email(self, regular_user):
        with pytest.raises(SystemExit):
            await add_user(regular_user.email, "password", skip_db_init=True)


class TestListUsers:
    """Tests for list_users."""

    @pytest.mark.asyncio
    async def test_list_users_empty(self, init_test_db, capsys):
        await list_users(skip_db_init=True)
        output = capsys.readouterr().out
        # With a shared DB, there may be users from other tests.
        # Just verify the function runs and produces expected header output.
        assert "Email" in output or "No users found" in output

    @pytest.mark.asyncio
    async def test_list_users_with_data(self, admin_user, regular_user, capsys):
        await list_users(skip_db_init=True)
        output = capsys.readouterr().out
        assert admin_user.email in output
        assert regular_user.email in output
        assert "Email" in output  # Header


class TestDisableUser:
    """Tests for disable_user."""

    @pytest.mark.asyncio
    async def test_disable_user(self, regular_user, capsys):
        await disable_user(regular_user.email, skip_db_init=True)
        output = capsys.readouterr().out
        assert "disabled" in output

        user = await User.find_one(User.email == regular_user.email)
        assert user.is_active is False

    @pytest.mark.asyncio
    async def test_disable_already_disabled(self, regular_user, capsys):
        regular_user.is_active = False
        await regular_user.save()
        await disable_user(regular_user.email, skip_db_init=True)
        output = capsys.readouterr().out
        assert "already disabled" in output

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, init_test_db):
        with pytest.raises(SystemExit):
            await disable_user("nobody@example.com", skip_db_init=True)


class TestEnableUser:
    """Tests for enable_user."""

    @pytest.mark.asyncio
    async def test_enable_user(self, regular_user, capsys):
        regular_user.is_active = False
        await regular_user.save()
        await enable_user(regular_user.email, skip_db_init=True)
        output = capsys.readouterr().out
        assert "enabled" in output

        user = await User.find_one(User.email == regular_user.email)
        assert user.is_active is True

    @pytest.mark.asyncio
    async def test_enable_already_active(self, regular_user, capsys):
        await enable_user(regular_user.email, skip_db_init=True)
        output = capsys.readouterr().out
        assert "already active" in output

    @pytest.mark.asyncio
    async def test_enable_nonexistent(self, init_test_db):
        with pytest.raises(SystemExit):
            await enable_user("nobody@example.com", skip_db_init=True)


class TestVerifyUser:
    """Tests for verify_user."""

    @pytest.mark.asyncio
    async def test_verify_user(self, regular_user, capsys):
        regular_user.is_verified = False
        await regular_user.save()
        await verify_user(regular_user.email, skip_db_init=True)
        output = capsys.readouterr().out
        assert "verified" in output

    @pytest.mark.asyncio
    async def test_verify_already_verified(self, regular_user, capsys):
        await verify_user(regular_user.email, skip_db_init=True)
        output = capsys.readouterr().out
        assert "already verified" in output

    @pytest.mark.asyncio
    async def test_verify_nonexistent(self, init_test_db):
        with pytest.raises(SystemExit):
            await verify_user("nobody@example.com", skip_db_init=True)


class TestRemoveUser:
    """Tests for remove_user."""

    @pytest.mark.asyncio
    async def test_remove_user_force(self, regular_user, capsys):
        await remove_user(regular_user.email, force=True, skip_db_init=True)
        output = capsys.readouterr().out
        assert "removed" in output

        user = await User.find_one(User.email == regular_user.email)
        assert user is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, init_test_db):
        with pytest.raises(SystemExit):
            await remove_user("nobody@example.com", force=True, skip_db_init=True)


class TestChangePassword:
    """Tests for change_password."""

    @pytest.mark.asyncio
    async def test_change_password(self, regular_user, capsys):
        await change_password(regular_user.email, "newpassword", skip_db_init=True)
        output = capsys.readouterr().out
        assert "updated" in output

        user = await User.find_one(User.email == regular_user.email)
        assert verify_password("newpassword", user.hashed_password)

    @pytest.mark.asyncio
    async def test_change_password_nonexistent(self, init_test_db):
        with pytest.raises(SystemExit):
            await change_password("nobody@example.com", "pass", skip_db_init=True)
