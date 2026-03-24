"""Unit tests for smart auto-import: confidence assessment, checksum, and duplicate detection."""

import hashlib

import pytest

from winebox.services.import_service.mapping import assess_mapping_confidence
from winebox.services.import_service.constants import MIN_CANONICAL_MATCHES


# =============================================================================
# Confidence Assessment Tests
# =============================================================================


def test_confidence_all_canonical_fields() -> None:
    """All canonical fields matched -> confident."""
    mapping = {
        "Wine Name": "name",
        "Producer": "winery",
        "Year": "vintage",
        "Grape": "grape_variety",
        "Country": "country",
        "Region": "region",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is True
    assert "name" in result["matched_fields"]
    assert len(result["matched_fields"]) == 6
    assert result["unmapped_headers"] == []


def test_confidence_name_and_one_other() -> None:
    """Name + one other canonical field -> confident (MIN_CANONICAL_MATCHES=2)."""
    mapping = {
        "Wine": "name",
        "Vintage": "vintage",
        "Rating": "custom:Rating",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is True
    assert set(result["matched_fields"]) == {"name", "vintage"}
    assert result["unmapped_headers"] == ["Rating"]


def test_confidence_name_only_not_confident() -> None:
    """Only name matched -> not confident (needs at least 2 canonical)."""
    mapping = {
        "Wine": "name",
        "Rating": "custom:Rating",
        "Score": "custom:Score",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is False
    assert result["matched_fields"] == ["name"]
    assert set(result["unmapped_headers"]) == {"Rating", "Score"}


def test_confidence_no_name_not_confident() -> None:
    """No name field matched -> never confident."""
    mapping = {
        "Producer": "winery",
        "Year": "vintage",
        "Country": "country",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is False
    assert "name" not in result["matched_fields"]


def test_confidence_all_custom_not_confident() -> None:
    """All custom fields -> not confident."""
    mapping = {
        "Col A": "custom:Col A",
        "Col B": "custom:Col B",
        "Col C": "custom:Col C",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is False
    assert result["matched_fields"] == []
    assert len(result["unmapped_headers"]) == 3


def test_confidence_skipped_fields_are_unmapped() -> None:
    """Skipped fields count as unmapped."""
    mapping = {
        "Wine": "name",
        "Vintage": "vintage",
        "Junk": "skip",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is True
    assert result["unmapped_headers"] == ["Junk"]


def test_confidence_non_canonical_wine_fields() -> None:
    """Non-canonical wine fields (like classification) don't count toward canonical matches."""
    mapping = {
        "Wine": "name",
        "Class": "classification",
        "Price": "price_tier",
    }
    result = assess_mapping_confidence(mapping)
    # Only "name" is canonical, classification and price_tier are not
    assert result["confident"] is False
    assert result["matched_fields"] == ["name"]


def test_confidence_duplicate_canonical_fields() -> None:
    """Two headers mapped to the same canonical field count as one match."""
    mapping = {
        "Wine": "name",
        "Wine Name": "name",
        "Year": "vintage",
    }
    result = assess_mapping_confidence(mapping)
    assert result["confident"] is True
    # "name" should appear only once in matched_fields
    assert result["matched_fields"].count("name") == 1


def test_min_canonical_matches_constant() -> None:
    """MIN_CANONICAL_MATCHES should be 2."""
    assert MIN_CANONICAL_MATCHES == 2


# =============================================================================
# Checksum Computation Tests
# =============================================================================


def test_same_content_same_checksum() -> None:
    """Same file content produces the same SHA-256 checksum."""
    content = b"Wine Name,Vintage,Country\nChateau Margaux,2015,France\n"
    hash1 = hashlib.sha256(content).hexdigest()
    hash2 = hashlib.sha256(content).hexdigest()
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex digest length


def test_different_content_different_checksum() -> None:
    """Different file content produces different checksums."""
    content1 = b"Wine Name,Vintage\nChateau Margaux,2015\n"
    content2 = b"Wine Name,Vintage\nChateau Margaux,2016\n"
    hash1 = hashlib.sha256(content1).hexdigest()
    hash2 = hashlib.sha256(content2).hexdigest()
    assert hash1 != hash2


def test_checksum_is_hex_string() -> None:
    """Checksum should be a lowercase hex string."""
    content = b"test data"
    checksum = hashlib.sha256(content).hexdigest()
    assert checksum == checksum.lower()
    assert all(c in "0123456789abcdef" for c in checksum)


# =============================================================================
# Schema Tests
# =============================================================================


def test_import_upload_response_defaults() -> None:
    """ImportUploadResponse should have correct defaults for new fields."""
    from winebox.schemas.import_schemas import ImportUploadResponse

    response = ImportUploadResponse(
        batch_id="test",
        filename="test.csv",
        row_count=10,
        headers=["name"],
        preview_rows=[],
        suggested_mapping={"name": "name"},
    )
    assert response.auto_import_eligible is False
    assert response.matched_canonical_fields == []
    assert response.unmapped_headers == []
    assert response.duplicate_of is None
    assert response.duplicate_filename is None
    assert response.duplicate_wines_created is None
    assert response.duplicate_mapping is None
    assert response.duplicate_unmapped_headers == []


def test_parsed_upload_request_with_checksum() -> None:
    """ParsedUploadRequest should accept file_checksum."""
    from winebox.schemas.import_schemas import ParsedUploadRequest

    request = ParsedUploadRequest(
        filename="test.csv",
        headers=["name"],
        preview_rows=[{"name": "test"}],
        row_count=1,
        file_checksum="abc123",
    )
    assert request.file_checksum == "abc123"


def test_parsed_upload_request_checksum_optional() -> None:
    """ParsedUploadRequest should work without file_checksum."""
    from winebox.schemas.import_schemas import ParsedUploadRequest

    request = ParsedUploadRequest(
        filename="test.csv",
        headers=["name"],
        preview_rows=[{"name": "test"}],
        row_count=1,
    )
    assert request.file_checksum is None


def test_import_batch_summary_with_new_fields() -> None:
    """ImportBatchSummary should include file_checksum and unmapped_headers."""
    from datetime import datetime, timezone
    from winebox.schemas.import_schemas import ImportBatchSummary

    summary = ImportBatchSummary(
        id="test",
        filename="test.csv",
        imported_at=datetime.now(timezone.utc),
        status="completed",
        row_count=10,
        wines_created=8,
        rows_skipped=2,
        file_checksum="abc123",
        unmapped_headers=["Rating", "Location"],
    )
    assert summary.file_checksum == "abc123"
    assert summary.unmapped_headers == ["Rating", "Location"]


# =============================================================================
# Model Tests
# =============================================================================


def test_import_batch_has_checksum_field() -> None:
    """ImportBatch model should have file_checksum and unmapped_headers fields."""
    from bson import ObjectId
    from winebox.models.import_batch import ImportBatch

    batch = ImportBatch(
        owner_id=ObjectId(),
        filename="test.csv",
        file_type="csv",
        file_checksum="abc123def456",
        unmapped_headers=["Rating"],
    )
    assert batch.file_checksum == "abc123def456"
    assert batch.unmapped_headers == ["Rating"]


def test_import_batch_checksum_defaults_to_none() -> None:
    """ImportBatch file_checksum should default to None."""
    from bson import ObjectId
    from winebox.models.import_batch import ImportBatch

    batch = ImportBatch(
        owner_id=ObjectId(),
        filename="test.csv",
        file_type="csv",
    )
    assert batch.file_checksum is None
    assert batch.unmapped_headers == []


def test_wine_has_import_batch_id_field() -> None:
    """Wine model should have import_batch_id field."""
    from bson import ObjectId
    from winebox.models.wine import Wine

    batch_id = ObjectId()
    wine = Wine(
        owner_id=ObjectId(),
        name="Test Wine",
        import_batch_id=batch_id,
    )
    assert wine.import_batch_id == batch_id


def test_wine_import_batch_id_defaults_to_none() -> None:
    """Wine import_batch_id should default to None."""
    from bson import ObjectId
    from winebox.models.wine import Wine

    wine = Wine(
        owner_id=ObjectId(),
        name="Test Wine",
    )
    assert wine.import_batch_id is None
