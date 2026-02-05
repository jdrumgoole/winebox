"""Tests for wine management endpoints."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient) -> None:
    """Test the health check endpoint."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_root_redirects_to_web_interface(client: AsyncClient) -> None:
    """Test that root URL redirects to the web interface."""
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 307  # Temporary redirect
    assert response.headers["location"] == "/static/index.html"


@pytest.mark.asyncio
async def test_checkin_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking in a wine."""
    # Create form data with image
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "winery": "Test Winery",
        "vintage": "2020",
        "grape_variety": "Cabernet Sauvignon",
        "region": "Napa Valley",
        "country": "United States",
        "quantity": "2",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    assert wine["name"] == "Test Wine"
    assert wine["winery"] == "Test Winery"
    assert wine["vintage"] == 2020
    assert wine["inventory"]["quantity"] == 2


@pytest.mark.asyncio
async def test_checkin_wine_minimal(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking in a wine with minimal data."""
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "quantity": "1",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    # Should have auto-detected or default name
    assert wine["name"] is not None
    assert wine["inventory"]["quantity"] == 1


@pytest.mark.asyncio
async def test_list_wines_empty(client: AsyncClient) -> None:
    """Test listing wines when cellar is empty."""
    response = await client.get("/api/wines")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_wines(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test listing wines after check-in."""
    # Check in a wine first
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "quantity": "1",
    }
    await client.post("/api/wines/checkin", files=files, data=data)

    # List wines
    response = await client.get("/api/wines")
    assert response.status_code == 200
    wines = response.json()
    assert len(wines) == 1
    assert wines[0]["name"] == "Test Wine"


@pytest.mark.asyncio
async def test_get_wine_detail(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test getting wine details."""
    # Check in a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Test Wine",
        "quantity": "3",
    }
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Get wine details
    response = await client.get(f"/api/wines/{wine_id}")
    assert response.status_code == 200

    wine = response.json()
    assert wine["name"] == "Test Wine"
    assert wine["inventory"]["quantity"] == 3
    assert len(wine["transactions"]) == 1
    assert wine["transactions"][0]["transaction_type"] == "CHECK_IN"


@pytest.mark.asyncio
async def test_get_wine_not_found(client: AsyncClient) -> None:
    """Test getting a wine that doesn't exist."""
    response = await client.get("/api/wines/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test updating wine metadata."""
    # Check in a wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Original Name", "quantity": "1"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Update wine
    response = await client.put(
        f"/api/wines/{wine_id}",
        json={"name": "Updated Name", "vintage": 2019}
    )
    assert response.status_code == 200

    wine = response.json()
    assert wine["name"] == "Updated Name"
    assert wine["vintage"] == 2019


@pytest.mark.asyncio
async def test_checkout_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking out wine."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "5"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Check out 2 bottles
    checkout_data = {"quantity": "2", "notes": "Dinner party"}
    response = await client.post(f"/api/wines/{wine_id}/checkout", data=checkout_data)
    assert response.status_code == 200

    wine = response.json()
    assert wine["inventory"]["quantity"] == 3


@pytest.mark.asyncio
async def test_checkout_exceeds_stock(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking out more than available stock."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "2"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Try to check out more than available
    checkout_data = {"quantity": "5"}
    response = await client.post(f"/api/wines/{wine_id}/checkout", data=checkout_data)
    assert response.status_code == 400
    assert "Not enough bottles" in response.json()["detail"]


@pytest.mark.asyncio
async def test_delete_wine(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test deleting a wine."""
    # Check in wine
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "1"}
    checkin_response = await client.post("/api/wines/checkin", files=files, data=data)
    wine_id = checkin_response.json()["id"]

    # Delete wine
    response = await client.delete(f"/api/wines/{wine_id}")
    assert response.status_code == 204

    # Verify deletion
    response = await client.get(f"/api/wines/{wine_id}")
    assert response.status_code == 404


# Security tests


@pytest.mark.asyncio
async def test_checkin_rejects_oversized_file(client: AsyncClient) -> None:
    """Test that oversized file uploads are rejected."""
    from winebox.config import settings

    # Create a file that exceeds the max upload size
    oversized_data = b"x" * (settings.max_upload_size_bytes + 1)

    files = {
        "front_label": ("test.png", io.BytesIO(oversized_data), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "1"}

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 413
    assert "exceeds maximum allowed size" in response.json()["detail"]


@pytest.mark.asyncio
async def test_checkin_rejects_invalid_file_type(client: AsyncClient) -> None:
    """Test that invalid file types are rejected."""
    # Create a fake executable file
    fake_exe = b"MZ" + b"\x00" * 100  # DOS header signature

    files = {
        "front_label": ("malware.exe", io.BytesIO(fake_exe), "application/x-msdownload"),
    }
    data = {"name": "Test Wine", "quantity": "1"}

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_scan_rejects_oversized_file(client: AsyncClient) -> None:
    """Test that scan endpoint rejects oversized files."""
    from winebox.config import settings

    # Create a file that exceeds the max upload size
    oversized_data = b"x" * (settings.max_upload_size_bytes + 1)

    files = {
        "front_label": ("test.png", io.BytesIO(oversized_data), "image/png"),
    }

    response = await client.post("/api/wines/scan", files=files)
    assert response.status_code == 413
    assert "exceeds maximum allowed size" in response.json()["detail"]


@pytest.mark.asyncio
async def test_checkin_with_prescanned_text(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test checking in wine with pre-scanned label text (skips rescanning).

    This tests the optimization where the frontend scans labels once on upload
    and passes the extracted text to checkin to avoid duplicate API calls.
    """
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }
    data = {
        "name": "Pre-scanned Wine",
        "winery": "Test Winery",
        "vintage": "2021",
        "quantity": "1",
        "front_label_text": "This is the pre-scanned front label text",
        "back_label_text": "This is the pre-scanned back label text",
    }

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201

    wine = response.json()
    assert wine["name"] == "Pre-scanned Wine"
    assert wine["front_label_text"] == "This is the pre-scanned front label text"
    assert wine["back_label_text"] == "This is the pre-scanned back label text"


@pytest.mark.asyncio
async def test_scan_endpoint_returns_parsed_data(client: AsyncClient, sample_image_bytes: bytes) -> None:
    """Test the scan endpoint returns parsed wine data and OCR text.

    This endpoint is used by the frontend to scan labels on upload
    before the user clicks 'Check In Wine'.
    """
    files = {
        "front_label": ("test.png", io.BytesIO(sample_image_bytes), "image/png"),
    }

    response = await client.post("/api/wines/scan", files=files)
    assert response.status_code == 200

    data = response.json()
    # Should have parsed, ocr, and method fields
    assert "parsed" in data
    assert "ocr" in data
    assert "method" in data
    # Method should be either claude_vision or tesseract
    assert data["method"] in ["claude_vision", "tesseract"]
    # OCR should have front_label_text
    assert "front_label_text" in data["ocr"]


@pytest.mark.asyncio
async def test_checkin_rejects_fake_image_with_wrong_magic_bytes(client: AsyncClient) -> None:
    """Test that files with valid extension but invalid content are rejected.

    This tests the magic byte verification - a file named .png but with
    non-image content should be rejected.
    """
    # Create fake "image" data - just random bytes, not a valid image
    fake_image = b"This is not an image, just some random text data"

    files = {
        "front_label": ("fake.png", io.BytesIO(fake_image), "image/png"),
    }
    data = {"name": "Test Wine", "quantity": "1"}

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 400
    assert "Invalid file content" in response.json()["detail"]


@pytest.mark.asyncio
async def test_checkin_accepts_jpeg_with_correct_magic_bytes(client: AsyncClient) -> None:
    """Test that valid JPEG files are accepted."""
    # Minimal valid JPEG (starts with FF D8 FF)
    # This is a 1x1 red pixel JPEG
    jpeg_data = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
        0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
        0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xDB, 0x20, 0xA8, 0xF1, 0x79, 0xC3,
        0x32, 0x01, 0xDD, 0x6F, 0xFF, 0xD9,
    ])

    files = {
        "front_label": ("test.jpg", io.BytesIO(jpeg_data), "image/jpeg"),
    }
    data = {"name": "Test Wine", "quantity": "1"}

    response = await client.post("/api/wines/checkin", files=files, data=data)
    assert response.status_code == 201
