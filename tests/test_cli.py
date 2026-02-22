"""Tests for CLI tools: user_admin and purge_data."""

import pytest
from datetime import datetime, timezone

from beanie import PydanticObjectId

from winebox.models.user import User
from winebox.models.wine import Wine
from winebox.models.transaction import Transaction, TransactionType
from winebox.services.auth import get_password_hash


# Test owner ID for wines/transactions that need one
TEST_OWNER_ID = PydanticObjectId("000000000000000000000001")


class TestUserAdmin:
    """Tests for user_admin CLI functions."""

    @pytest.mark.asyncio
    async def test_add_user(self, init_test_db):
        """Test adding a new user."""
        from winebox.cli.user_admin import add_user

        await add_user("newuser@example.com", "password123", is_admin=False, skip_db_init=True)

        user = await User.find_one(User.email == "newuser@example.com")
        assert user is not None
        assert user.email == "newuser@example.com"
        assert user.is_superuser is False
        assert user.is_active is True
        assert user.is_verified is True

    @pytest.mark.asyncio
    async def test_add_admin_user(self, init_test_db):
        """Test adding an admin user."""
        from winebox.cli.user_admin import add_user

        await add_user("admin@example.com", "adminpass", is_admin=True, skip_db_init=True)

        user = await User.find_one(User.email == "admin@example.com")
        assert user is not None
        assert user.is_superuser is True

    @pytest.mark.asyncio
    async def test_add_duplicate_user_fails(self, init_test_db):
        """Test that adding a duplicate user fails."""
        from winebox.cli.user_admin import add_user

        await add_user("duplicate@example.com", "password123", skip_db_init=True)

        # Second add should fail with sys.exit(1)
        with pytest.raises(SystemExit) as exc_info:
            await add_user("duplicate@example.com", "password456", skip_db_init=True)
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_list_users(self, init_test_db, capsys):
        """Test listing users."""
        from winebox.cli.user_admin import list_users

        # Create some test users
        for i in range(3):
            user = User(
                email=f"user{i}@example.com",
                hashed_password=get_password_hash("password"),
                is_active=True,
                is_verified=True,
                is_superuser=(i == 0),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await user.insert()

        await list_users(skip_db_init=True)
        captured = capsys.readouterr()

        assert "user0@example.com" in captured.out
        assert "user1@example.com" in captured.out
        assert "user2@example.com" in captured.out

    @pytest.mark.asyncio
    async def test_list_users_empty(self, init_test_db, capsys):
        """Test listing users when none exist."""
        from winebox.cli.user_admin import list_users

        await list_users(skip_db_init=True)
        captured = capsys.readouterr()

        assert "No users found" in captured.out

    @pytest.mark.asyncio
    async def test_disable_user(self, init_test_db, capsys):
        """Test disabling a user."""
        from winebox.cli.user_admin import disable_user

        # Create a user
        user = User(
            email="todisable@example.com",
            hashed_password=get_password_hash("password"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        await disable_user("todisable@example.com", skip_db_init=True)

        # Reload and check
        user = await User.find_one(User.email == "todisable@example.com")
        assert user.is_active is False

        captured = capsys.readouterr()
        assert "disabled" in captured.out.lower()

    @pytest.mark.asyncio
    async def test_disable_nonexistent_user_fails(self, init_test_db):
        """Test that disabling a nonexistent user fails."""
        from winebox.cli.user_admin import disable_user

        with pytest.raises(SystemExit) as exc_info:
            await disable_user("nonexistent@example.com", skip_db_init=True)
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_enable_user(self, init_test_db, capsys):
        """Test enabling a disabled user."""
        from winebox.cli.user_admin import enable_user

        # Create a disabled user
        user = User(
            email="toenable@example.com",
            hashed_password=get_password_hash("password"),
            is_active=False,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        await enable_user("toenable@example.com", skip_db_init=True)

        # Reload and check
        user = await User.find_one(User.email == "toenable@example.com")
        assert user.is_active is True

        captured = capsys.readouterr()
        assert "enabled" in captured.out.lower()

    @pytest.mark.asyncio
    async def test_remove_user(self, init_test_db, capsys):
        """Test removing a user."""
        from winebox.cli.user_admin import remove_user

        # Create a user
        user = User(
            email="toremove@example.com",
            hashed_password=get_password_hash("password"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        # Remove with force=True to skip confirmation
        await remove_user("toremove@example.com", force=True, skip_db_init=True)

        # Check user is gone
        user = await User.find_one(User.email == "toremove@example.com")
        assert user is None

        captured = capsys.readouterr()
        assert "removed" in captured.out.lower()

    @pytest.mark.asyncio
    async def test_change_password(self, init_test_db, capsys):
        """Test changing a user's password."""
        from winebox.cli.user_admin import change_password
        from winebox.services.auth import verify_password

        # Create a user
        user = User(
            email="tochange@example.com",
            hashed_password=get_password_hash("oldpassword"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        await change_password("tochange@example.com", "newpassword123", skip_db_init=True)

        # Reload and verify new password works
        user = await User.find_one(User.email == "tochange@example.com")
        assert verify_password("newpassword123", user.hashed_password)
        assert not verify_password("oldpassword", user.hashed_password)

        captured = capsys.readouterr()
        assert "updated" in captured.out.lower()


class TestPurgeData:
    """Tests for purge_data CLI functions."""

    @pytest.mark.asyncio
    async def test_count_wine_data(self, init_test_db):
        """Test counting wine data."""
        from winebox.cli.purge_data import count_wine_data

        # Create some wines and transactions
        wine = Wine(
            owner_id=TEST_OWNER_ID,
            name="Test Wine",
            front_label_image_path="test.jpg",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await wine.insert()

        transaction = Transaction(
            owner_id=TEST_OWNER_ID,
            wine_id=wine.id,
            transaction_type=TransactionType.CHECK_IN,
            quantity=3,
            created_at=datetime.now(timezone.utc),
        )
        await transaction.insert()

        counts = await count_wine_data(skip_db_init=True)

        assert counts["wines"] == 1
        assert counts["transactions"] == 1

    @pytest.mark.asyncio
    async def test_count_all_data(self, init_test_db):
        """Test counting all data."""
        from winebox.cli.purge_data import count_all_data

        # Create user, wine, and transaction
        user = User(
            email="counttest@example.com",
            hashed_password=get_password_hash("password"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        wine = Wine(
            owner_id=user.id,
            name="Count Test Wine",
            front_label_image_path="test.jpg",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await wine.insert()

        transaction = Transaction(
            owner_id=user.id,
            wine_id=wine.id,
            transaction_type=TransactionType.CHECK_IN,
            quantity=1,
            created_at=datetime.now(timezone.utc),
        )
        await transaction.insert()

        counts = await count_all_data(skip_db_init=True)

        assert counts["users"] == 1
        assert counts["wines"] == 1
        assert counts["transactions"] == 1

    @pytest.mark.asyncio
    async def test_remove_user_via_purge(self, init_test_db):
        """Test removing a user via purge_data."""
        from winebox.cli.purge_data import remove_user

        # Create a user
        user = User(
            email="purgeuser@example.com",
            hashed_password=get_password_hash("password"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        result = await remove_user("purgeuser@example.com", skip_db_init=True)

        assert result.get("deleted") is True
        assert result.get("email") == "purgeuser@example.com"

        # Verify user is gone
        user = await User.find_one(User.email == "purgeuser@example.com")
        assert user is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_user_via_purge(self, init_test_db):
        """Test removing a nonexistent user via purge_data."""
        from winebox.cli.purge_data import remove_user

        result = await remove_user("nonexistent@example.com", skip_db_init=True)

        assert "error" in result

    @pytest.mark.asyncio
    async def test_purge_wine_data(self, init_test_db):
        """Test purging all wine data."""
        from winebox.cli.purge_data import purge_wine_data

        # Create a user (should be preserved)
        user = User(
            email="preserved@example.com",
            hashed_password=get_password_hash("password"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        # Create wines and transactions
        for i in range(3):
            wine = Wine(
                owner_id=user.id,
                name=f"Wine {i}",
                front_label_image_path=f"test{i}.jpg",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await wine.insert()

            transaction = Transaction(
                owner_id=user.id,
                wine_id=wine.id,
                transaction_type=TransactionType.CHECK_IN,
                quantity=1,
                created_at=datetime.now(timezone.utc),
            )
            await transaction.insert()

        # Verify data exists
        assert await Wine.count() == 3
        assert await Transaction.count() == 3
        assert await User.count() == 1

        result = await purge_wine_data(skip_db_init=True)

        assert result["deleted_wines"] == 3
        assert result["deleted_transactions"] == 3

        # Verify wines and transactions are gone
        assert await Wine.count() == 0
        assert await Transaction.count() == 0

        # Verify user is preserved
        assert await User.count() == 1

    @pytest.mark.asyncio
    async def test_purge_all_data(self, init_test_db):
        """Test purging all data."""
        from winebox.cli.purge_data import purge_all_data

        # Create user, wine, and transaction
        user = User(
            email="todelete@example.com",
            hashed_password=get_password_hash("password"),
            is_active=True,
            is_verified=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await user.insert()

        wine = Wine(
            owner_id=user.id,
            name="To Delete Wine",
            front_label_image_path="test.jpg",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await wine.insert()

        transaction = Transaction(
            owner_id=user.id,
            wine_id=wine.id,
            transaction_type=TransactionType.CHECK_IN,
            quantity=1,
            created_at=datetime.now(timezone.utc),
        )
        await transaction.insert()

        # Verify data exists
        assert await Wine.count() == 1
        assert await Transaction.count() == 1
        assert await User.count() == 1

        result = await purge_all_data(skip_db_init=True)

        assert result["deleted_wines"] == 1
        assert result["deleted_transactions"] == 1
        assert result["deleted_users"] == 1

        # Verify everything is gone
        assert await Wine.count() == 0
        assert await Transaction.count() == 0
        assert await User.count() == 0


class TestPurgeImages:
    """Tests for image purging functionality."""

    def test_purge_images_empty_dir(self, tmp_path):
        """Test purging when images directory is empty."""
        import winebox.cli.purge_data as purge_module

        # Create empty images directory
        images_dir = tmp_path / "images"
        images_dir.mkdir()

        original_func = purge_module.get_images_path
        purge_module.get_images_path = lambda: images_dir
        try:
            count = purge_module.purge_images()
            assert count == 0
        finally:
            purge_module.get_images_path = original_func

    def test_purge_images_with_files(self, tmp_path):
        """Test purging when images directory has files."""
        import winebox.cli.purge_data as purge_module

        # Create images directory with files
        images_dir = tmp_path / "images"
        images_dir.mkdir()
        (images_dir / "test1.jpg").write_bytes(b"test image 1")
        (images_dir / "test2.jpg").write_bytes(b"test image 2")
        (images_dir / "test3.png").write_bytes(b"test image 3")

        original_func = purge_module.get_images_path
        purge_module.get_images_path = lambda: images_dir
        try:
            count = purge_module.purge_images()
            assert count == 3
            # Directory should be recreated empty
            assert images_dir.exists()
            assert len(list(images_dir.glob("*"))) == 0
        finally:
            purge_module.get_images_path = original_func

    def test_purge_images_nonexistent_dir(self, tmp_path):
        """Test purging when images directory doesn't exist."""
        import winebox.cli.purge_data as purge_module

        images_dir = tmp_path / "nonexistent"

        original_func = purge_module.get_images_path
        purge_module.get_images_path = lambda: images_dir
        try:
            count = purge_module.purge_images()
            assert count == 0
        finally:
            purge_module.get_images_path = original_func
