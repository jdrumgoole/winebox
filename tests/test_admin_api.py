"""Tests for admin user management API endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_activate_user(admin_client: AsyncClient, client: AsyncClient) -> None:
    """Test activating a deactivated user."""
    # Get the non-admin user's ID
    users_resp = await admin_client.get("/admin/api/users")
    users = users_resp.json()["users"]
    # Find non-admin user (created by client fixture)
    target = next(u for u in users if not u["is_superuser"])

    # Deactivate then reactivate
    resp = await admin_client.patch(f"/admin/api/users/{target['id']}/deactivate")
    assert resp.status_code == 200

    resp = await admin_client.patch(f"/admin/api/users/{target['id']}/activate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "activated"


@pytest.mark.asyncio
async def test_deactivate_user(admin_client: AsyncClient, client: AsyncClient) -> None:
    """Test deactivating a user."""
    users_resp = await admin_client.get("/admin/api/users")
    target = next(u for u in users_resp.json()["users"] if not u["is_superuser"])

    resp = await admin_client.patch(f"/admin/api/users/{target['id']}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deactivated"

    # Re-activate for cleanup
    await admin_client.patch(f"/admin/api/users/{target['id']}/activate")


@pytest.mark.asyncio
async def test_cannot_deactivate_self(admin_client: AsyncClient) -> None:
    """Test that admin cannot deactivate themselves."""
    # Get admin's own user ID
    me_resp = await admin_client.get("/api/auth/me")
    my_id = me_resp.json()["id"]

    resp = await admin_client.patch(f"/admin/api/users/{my_id}/deactivate")
    assert resp.status_code == 400
    assert "your own account" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_make_and_remove_admin(admin_client: AsyncClient, client: AsyncClient) -> None:
    """Test granting and revoking admin privileges."""
    users_resp = await admin_client.get("/admin/api/users")
    target = next(u for u in users_resp.json()["users"] if not u["is_superuser"])

    # Make admin
    resp = await admin_client.patch(f"/admin/api/users/{target['id']}/make-admin")
    assert resp.status_code == 200
    assert resp.json()["status"] == "admin_granted"

    # Remove admin
    resp = await admin_client.patch(f"/admin/api/users/{target['id']}/remove-admin")
    assert resp.status_code == 200
    assert resp.json()["status"] == "admin_removed"


@pytest.mark.asyncio
async def test_cannot_remove_admin_self(admin_client: AsyncClient) -> None:
    """Test that admin cannot remove their own admin role."""
    me_resp = await admin_client.get("/api/auth/me")
    my_id = me_resp.json()["id"]

    resp = await admin_client.patch(f"/admin/api/users/{my_id}/remove-admin")
    assert resp.status_code == 400
    assert "your own account" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_verify_user(admin_client: AsyncClient, client: AsyncClient) -> None:
    """Test manually verifying a user."""
    users_resp = await admin_client.get("/admin/api/users")
    target = next(u for u in users_resp.json()["users"] if not u["is_superuser"])

    resp = await admin_client.patch(f"/admin/api/users/{target['id']}/verify")
    assert resp.status_code == 200
    assert resp.json()["status"] == "verified"


@pytest.mark.asyncio
async def test_delete_user(admin_client: AsyncClient) -> None:
    """Test deleting a user and all their data."""
    # Register a throwaway user to delete
    reg_resp = await admin_client.post(
        "/api/auth/register",
        json={"email": "delete_me@example.com", "password": "securepassword123"},
    )
    user_id = reg_resp.json()["id"]

    resp = await admin_client.delete(f"/admin/api/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

    # Verify user is gone
    resp2 = await admin_client.patch(f"/admin/api/users/{user_id}/activate")
    assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_cannot_delete_self(admin_client: AsyncClient) -> None:
    """Test that admin cannot delete themselves."""
    me_resp = await admin_client.get("/api/auth/me")
    my_id = me_resp.json()["id"]

    resp = await admin_client.delete(f"/admin/api/users/{my_id}")
    assert resp.status_code == 400
    assert "your own account" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_non_admin_rejected(client: AsyncClient) -> None:
    """Test that non-admin users cannot access admin endpoints."""
    resp = await client.patch("/admin/api/users/fakeid/activate")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_user_not_found(admin_client: AsyncClient) -> None:
    """Test 404 for non-existent user ID."""
    resp = await admin_client.patch("/admin/api/users/000000000000000000000000/activate")
    assert resp.status_code == 404
