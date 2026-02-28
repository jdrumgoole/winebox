"""Tests for wine ownership and data isolation between users."""

import io
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from winebox.models import User
from winebox.services.auth import create_access_token, get_password_hash


@pytest_asyncio.fixture(scope="function")
async def two_users_clients(init_test_db):
    """Create two authenticated clients for different users.

    Returns a tuple of (user1_client, user2_client).
    """
    from tests.conftest import get_test_app

    # Create user 1
    user1 = User(
        email="user1@example.com",
        hashed_password=get_password_hash("password1"),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await user1.insert()
    token1 = create_access_token(data={"sub": "user1@example.com"})

    # Create user 2
    user2 = User(
        email="user2@example.com",
        hashed_password=get_password_hash("password2"),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    await user2.insert()
    token2 = create_access_token(data={"sub": "user2@example.com"})

    app = get_test_app()

    # Create clients for both users
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token1}"},
    ) as client1:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token2}"},
        ) as client2:
            yield client1, client2


@pytest.fixture
def sample_image_bytes() -> bytes:
    """Create sample image bytes for testing."""
    # Minimal valid PNG (1x1 pixel)
    png_data = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01,
        0x00, 0x00, 0x00, 0x01,
        0x08, 0x02,
        0x00, 0x00, 0x00,
        0x90, 0x77, 0x53, 0xDE,
        0x00, 0x00, 0x00, 0x0C,
        0x49, 0x44, 0x41, 0x54,
        0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F, 0x00,
        0x05, 0xFE, 0x02, 0xFE,
        0xA3, 0x1A, 0x8D, 0xEB,
        0x00, 0x00, 0x00, 0x00,
        0x49, 0x45, 0x4E, 0x44,
        0xAE, 0x42, 0x60, 0x82,
    ])
    return png_data


# =============================================================================
# OWNERSHIP ISOLATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_user_cannot_see_other_users_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user1's wines are not visible to user2."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "3"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201
    user1_wine_id = response.json()["id"]

    # User 1 can see their wine
    response = await client1.get("/api/wines")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "User1 Wine"

    # User 2 cannot see user1's wine
    response = await client2.get("/api/wines")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 0

    # User 2 gets 404 when trying to access user1's wine directly
    response = await client2.get(f"/api/wines/{user1_wine_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_modify_other_users_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user2 cannot update or delete user1's wines."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "3"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201
    user1_wine_id = response.json()["id"]

    # User 2 cannot update user1's wine
    response = await client2.put(
        f"/api/wines/{user1_wine_id}",
        json={"name": "Hacked Wine"}
    )
    assert response.status_code == 404

    # User 2 cannot delete user1's wine
    response = await client2.delete(f"/api/wines/{user1_wine_id}")
    assert response.status_code == 404

    # Verify wine is still unchanged
    response = await client1.get(f"/api/wines/{user1_wine_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "User1 Wine"


@pytest.mark.asyncio
async def test_user_cannot_checkout_other_users_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user2 cannot checkout wines from user1's cellar."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "5"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201
    user1_wine_id = response.json()["id"]

    # User 2 cannot checkout user1's wine
    checkout_data = {"quantity": "1"}
    response = await client2.post(
        f"/api/wines/{user1_wine_id}/checkout",
        data=checkout_data
    )
    assert response.status_code == 404

    # Verify wine quantity is unchanged
    response = await client1.get(f"/api/wines/{user1_wine_id}")
    assert response.status_code == 200
    assert response.json()["inventory"]["quantity"] == 5


@pytest.mark.asyncio
async def test_user_cannot_see_other_users_transactions(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user2 cannot see user1's transactions."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine (creates a transaction)
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "3"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    # User 1 can see their transactions
    response = await client1.get("/api/transactions")
    assert response.status_code == 200
    transactions = response.json()
    assert len(transactions) == 1
    assert transactions[0]["transaction_type"] == "CHECK_IN"

    # User 2 cannot see user1's transactions
    response = await client2.get("/api/transactions")
    assert response.status_code == 200
    transactions = response.json()
    assert len(transactions) == 0


@pytest.mark.asyncio
async def test_cellar_summary_shows_only_own_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that cellar summary only counts user's own wines."""
    client1, client2 = two_users_clients

    # User 1 checks in 3 bottles
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "3"}
    await client1.post("/api/wines/checkin", files=files, data=data)

    # User 2 checks in 2 bottles
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User2 Wine", "quantity": "2"}
    await client2.post("/api/wines/checkin", files=files, data=data)

    # User 1's cellar summary should show 3 bottles
    response = await client1.get("/api/cellar/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_bottles"] == 3
    assert summary["unique_wines"] == 1

    # User 2's cellar summary should show 2 bottles
    response = await client2.get("/api/cellar/summary")
    assert response.status_code == 200
    summary = response.json()
    assert summary["total_bottles"] == 2
    assert summary["unique_wines"] == 1


@pytest.mark.asyncio
async def test_cellar_inventory_shows_only_own_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that cellar inventory only shows user's own wines."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "1"}
    await client1.post("/api/wines/checkin", files=files, data=data)

    # User 2 checks in a different wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User2 Wine", "quantity": "1"}
    await client2.post("/api/wines/checkin", files=files, data=data)

    # User 1's cellar should only show their wine
    response = await client1.get("/api/cellar")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "User1 Wine"

    # User 2's cellar should only show their wine
    response = await client2.get("/api/cellar")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "User2 Wine"


@pytest.mark.asyncio
async def test_search_only_searches_own_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that search only returns user's own wines."""
    client1, client2 = two_users_clients

    # User 1 checks in a Bordeaux wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "Bordeaux Classic", "region": "Bordeaux", "quantity": "1"}
    await client1.post("/api/wines/checkin", files=files, data=data)

    # User 2 checks in a different Bordeaux wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "Bordeaux Reserve", "region": "Bordeaux", "quantity": "1"}
    await client2.post("/api/wines/checkin", files=files, data=data)

    # User 1 searches for Bordeaux - should only find their wine
    response = await client1.get("/api/search?region=Bordeaux")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "Bordeaux Classic"

    # User 2 searches for Bordeaux - should only find their wine
    response = await client2.get("/api/search?region=Bordeaux")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "Bordeaux Reserve"


@pytest.mark.asyncio
async def test_export_only_exports_own_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that export only includes user's own wines."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Export Wine", "quantity": "1"}
    await client1.post("/api/wines/checkin", files=files, data=data)

    # User 2 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User2 Export Wine", "quantity": "1"}
    await client2.post("/api/wines/checkin", files=files, data=data)

    # User 1 exports wines - should only include their wine
    response = await client1.get("/api/export/wines?format=json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["wines"]) == 1
    assert data["wines"][0]["name"] == "User1 Export Wine"

    # User 2 exports wines - should only include their wine
    response = await client2.get("/api/export/wines?format=json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["wines"]) == 1
    assert data["wines"][0]["name"] == "User2 Export Wine"


@pytest.mark.asyncio
async def test_export_transactions_only_exports_own(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that transaction export only includes user's own transactions."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "1"}
    await client1.post("/api/wines/checkin", files=files, data=data)

    # User 2 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User2 Wine", "quantity": "1"}
    await client2.post("/api/wines/checkin", files=files, data=data)

    # User 1 exports transactions - should only include their transaction
    response = await client1.get("/api/export/transactions?format=json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["transactions"]) == 1

    # User 2 exports transactions - should only include their transaction
    response = await client2.get("/api/export/transactions?format=json")
    assert response.status_code == 200
    data = response.json()
    assert len(data["transactions"]) == 1


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_wine_grapes(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user2 cannot access user1's wine grape blend."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "1"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    user1_wine_id = response.json()["id"]

    # User 1 can access their wine's grape info
    response = await client1.get(f"/api/wines/{user1_wine_id}/grapes")
    assert response.status_code == 200

    # User 2 cannot access user1's wine grapes
    response = await client2.get(f"/api/wines/{user1_wine_id}/grapes")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_access_other_users_wine_scores(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user2 cannot access user1's wine scores."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "1"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    user1_wine_id = response.json()["id"]

    # User 1 can access their wine's scores
    response = await client1.get(f"/api/wines/{user1_wine_id}/scores")
    assert response.status_code == 200

    # User 2 cannot access user1's wine scores
    response = await client2.get(f"/api/wines/{user1_wine_id}/scores")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_user_cannot_add_scores_to_other_users_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that user2 cannot add scores to user1's wines."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "1"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    user1_wine_id = response.json()["id"]

    # User 2 cannot add a score to user1's wine
    score_data = {
        "source": "Wine Spectator",
        "score": 95,
        "score_type": "100_point",
    }
    response = await client2.post(
        f"/api/wines/{user1_wine_id}/scores",
        json=score_data
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_both_users_can_manage_their_own_wines_independently(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that both users can fully manage their own wines independently."""
    client1, client2 = two_users_clients

    # User 1 checks in and manages a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "5"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201
    user1_wine_id = response.json()["id"]

    # User 2 checks in and manages their own wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User2 Wine", "quantity": "3"}
    response = await client2.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201
    user2_wine_id = response.json()["id"]

    # User 1 updates their wine
    response = await client1.put(
        f"/api/wines/{user1_wine_id}",
        json={"name": "User1 Wine Updated"}
    )
    assert response.status_code == 200

    # User 2 updates their wine
    response = await client2.put(
        f"/api/wines/{user2_wine_id}",
        json={"name": "User2 Wine Updated"}
    )
    assert response.status_code == 200

    # User 1 checks out from their wine
    response = await client1.post(
        f"/api/wines/{user1_wine_id}/checkout",
        data={"quantity": "2"}
    )
    assert response.status_code == 200
    assert response.json()["inventory"]["quantity"] == 3

    # User 2 checks out from their wine
    response = await client2.post(
        f"/api/wines/{user2_wine_id}/checkout",
        data={"quantity": "1"}
    )
    assert response.status_code == 200
    assert response.json()["inventory"]["quantity"] == 2

    # Verify final states are independent
    response = await client1.get(f"/api/wines/{user1_wine_id}")
    assert response.json()["name"] == "User1 Wine Updated"
    assert response.json()["inventory"]["quantity"] == 3

    response = await client2.get(f"/api/wines/{user2_wine_id}")
    assert response.json()["name"] == "User2 Wine Updated"
    assert response.json()["inventory"]["quantity"] == 2


@pytest.mark.asyncio
async def test_delete_all_wines_only_deletes_own_wines(
    two_users_clients, sample_image_bytes
) -> None:
    """Test that deleting all wines only affects the current user's collection."""
    client1, client2 = two_users_clients

    # User 1 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User1 Wine", "quantity": "2"}
    response = await client1.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    # User 2 checks in a wine
    files = {"front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png")}
    data = {"name": "User2 Wine", "quantity": "3"}
    response = await client2.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    # User 1 deletes all their wines
    response = await client1.delete("/api/wines/all")
    assert response.status_code == 200
    assert response.json()["deleted_wines"] == 1

    # User 1 has no wines
    response = await client1.get("/api/wines")
    assert response.json() == []

    # User 2's wine survives
    response = await client2.get("/api/wines")
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "User2 Wine"
    assert wines[0]["inventory"]["quantity"] == 3
