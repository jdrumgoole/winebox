"""Tests for the WineBox configuration system."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from winebox.config.loader import (
    apply_env_overrides,
    find_config_file,
    find_secrets_file,
    get_config_search_paths,
    get_secrets_search_paths,
    load_config,
    load_secrets,
    load_toml_file,
    parse_env_file,
)
from winebox.config.schema import (
    AuthConfig,
    DatabaseConfig,
    EmailConfig,
    OCRConfig,
    SecretsConfig,
    ServerConfig,
    StorageConfig,
    WineboxConfig,
)
from winebox.config.settings import Settings, get_settings, reset_settings


class TestSchemaDefaults:
    """Test default values in schema models."""

    def test_server_config_defaults(self):
        """Test ServerConfig has correct defaults."""
        config = ServerConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.workers == 2
        assert config.debug is False
        assert config.enforce_https is False
        assert config.rate_limit_per_minute == 60

    def test_database_config_defaults(self):
        """Test DatabaseConfig has correct defaults."""
        config = DatabaseConfig()
        assert config.mongodb_url == "mongodb://localhost:27017"
        assert config.mongodb_database == "winebox"

    def test_storage_config_defaults(self):
        """Test StorageConfig has correct defaults."""
        config = StorageConfig()
        assert config.data_dir == Path("data")
        assert config.log_dir == Path("data/logs")
        assert config.max_upload_mb == 10
        assert config.images_dir == Path("data/images")
        assert config.max_upload_bytes == 10 * 1024 * 1024

    def test_ocr_config_defaults(self):
        """Test OCRConfig has correct defaults."""
        config = OCRConfig()
        assert config.use_claude_vision is True
        assert config.tesseract_lang == "eng"
        assert config.tesseract_cmd is None

    def test_auth_config_defaults(self):
        """Test AuthConfig has correct defaults."""
        config = AuthConfig()
        assert config.enabled is True
        assert config.registration_enabled is True
        assert config.email_verification_required is True
        assert config.auth_rate_limit_per_minute == 30

    def test_email_config_defaults(self):
        """Test EmailConfig has correct defaults."""
        config = EmailConfig()
        assert config.backend == "console"
        assert config.from_address == "noreply@winebox.app"
        assert config.from_name == "WineBox"
        assert config.frontend_url == "http://localhost:8000"
        assert config.aws_region == "eu-west-1"

    def test_winebox_config_defaults(self):
        """Test WineboxConfig has correct defaults."""
        config = WineboxConfig()
        assert config.app_name == "WineBox"
        assert isinstance(config.server, ServerConfig)
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.storage, StorageConfig)
        assert isinstance(config.ocr, OCRConfig)
        assert isinstance(config.auth, AuthConfig)
        assert isinstance(config.email, EmailConfig)

    def test_secrets_config_defaults(self):
        """Test SecretsConfig has correct defaults."""
        config = SecretsConfig()
        assert config.secret_key is None
        assert config.anthropic_api_key is None
        assert config.aws_access_key_id is None
        assert config.aws_secret_access_key is None


class TestConfigSearchPaths:
    """Test configuration file search paths."""

    def test_config_search_paths_order(self):
        """Test config search paths are in correct priority order."""
        paths = get_config_search_paths()
        assert len(paths) == 3
        assert paths[0] == Path.cwd() / "config.toml"
        assert paths[1] == Path.home() / ".config" / "winebox" / "config.toml"
        assert paths[2] == Path("/etc/winebox/config.toml")

    def test_secrets_search_paths_order(self):
        """Test secrets search paths are in correct priority order."""
        paths = get_secrets_search_paths()
        assert len(paths) == 3
        assert paths[0] == Path.cwd() / "secrets.env"
        assert paths[1] == Path.home() / ".config" / "winebox" / "secrets.env"
        assert paths[2] == Path("/etc/winebox/secrets.env")


class TestTomlLoading:
    """Test TOML file loading."""

    def test_load_toml_file(self, tmp_path):
        """Test loading a valid TOML file."""
        toml_content = """
app_name = "TestApp"

[server]
host = "0.0.0.0"
port = 9000
debug = true

[database]
mongodb_url = "mongodb://testhost:27017"
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        data = load_toml_file(config_file)
        assert data["app_name"] == "TestApp"
        assert data["server"]["host"] == "0.0.0.0"
        assert data["server"]["port"] == 9000
        assert data["server"]["debug"] is True
        assert data["database"]["mongodb_url"] == "mongodb://testhost:27017"

    def test_load_config_from_file(self, tmp_path):
        """Test load_config with a specific file."""
        toml_content = """
app_name = "CustomApp"

[server]
port = 5000
workers = 4

[ocr]
use_claude_vision = false
"""
        config_file = tmp_path / "config.toml"
        config_file.write_text(toml_content)

        config = load_config(config_file)
        assert config.app_name == "CustomApp"
        assert config.server.port == 5000
        assert config.server.workers == 4
        assert config.ocr.use_claude_vision is False
        # Defaults should still apply
        assert config.server.host == "127.0.0.1"
        assert config.database.mongodb_url == "mongodb://localhost:27017"


class TestEnvFileParsing:
    """Test .env file parsing."""

    def test_parse_simple_env_file(self, tmp_path):
        """Test parsing a simple .env file."""
        env_content = """
WINEBOX_SECRET_KEY=my-secret-key
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
"""
        env_file = tmp_path / "secrets.env"
        env_file.write_text(env_content)

        result = parse_env_file(env_file)
        assert result["WINEBOX_SECRET_KEY"] == "my-secret-key"
        assert result["AWS_ACCESS_KEY_ID"] == "AKIAIOSFODNN7EXAMPLE"

    def test_parse_env_file_with_quotes(self, tmp_path):
        """Test parsing .env file with quoted values."""
        env_content = '''
KEY1="double quoted value"
KEY2='single quoted value'
KEY3=unquoted value
'''
        env_file = tmp_path / "test.env"
        env_file.write_text(env_content)

        result = parse_env_file(env_file)
        assert result["KEY1"] == "double quoted value"
        assert result["KEY2"] == "single quoted value"
        assert result["KEY3"] == "unquoted value"

    def test_parse_env_file_skips_comments(self, tmp_path):
        """Test that comments are skipped."""
        env_content = """
# This is a comment
KEY1=value1
# Another comment
KEY2=value2
"""
        env_file = tmp_path / "test.env"
        env_file.write_text(env_content)

        result = parse_env_file(env_file)
        assert len(result) == 2
        assert result["KEY1"] == "value1"
        assert result["KEY2"] == "value2"

    def test_parse_env_file_skips_empty_lines(self, tmp_path):
        """Test that empty lines are skipped."""
        env_content = """
KEY1=value1

KEY2=value2

"""
        env_file = tmp_path / "test.env"
        env_file.write_text(env_content)

        result = parse_env_file(env_file)
        assert len(result) == 2


class TestEnvOverrides:
    """Test environment variable overrides."""

    def test_apply_server_overrides(self):
        """Test server configuration overrides."""
        config_dict = {}

        with patch.dict(os.environ, {"WINEBOX_HOST": "0.0.0.0", "WINEBOX_PORT": "3000"}):
            apply_env_overrides(config_dict)

        assert config_dict["server"]["host"] == "0.0.0.0"
        assert config_dict["server"]["port"] == 3000

    def test_apply_database_overrides(self):
        """Test database configuration overrides."""
        config_dict = {}

        with patch.dict(
            os.environ,
            {
                "WINEBOX_MONGODB_URL": "mongodb://custom:27017",
                "WINEBOX_MONGODB_DATABASE": "custom_db",
            },
        ):
            apply_env_overrides(config_dict)

        assert config_dict["database"]["mongodb_url"] == "mongodb://custom:27017"
        assert config_dict["database"]["mongodb_database"] == "custom_db"

    def test_apply_boolean_override_true(self):
        """Test boolean overrides with 'true' value."""
        config_dict = {}

        with patch.dict(os.environ, {"WINEBOX_DEBUG": "true"}):
            apply_env_overrides(config_dict)

        assert config_dict["server"]["debug"] is True

    def test_apply_boolean_override_false(self):
        """Test boolean overrides with 'false' value."""
        config_dict = {"server": {"debug": True}}

        with patch.dict(os.environ, {"WINEBOX_DEBUG": "false"}):
            apply_env_overrides(config_dict)

        assert config_dict["server"]["debug"] is False


class TestSecretsLoading:
    """Test secrets loading."""

    def test_load_secrets_from_file(self, tmp_path):
        """Test loading secrets from a file."""
        secrets_content = """
WINEBOX_SECRET_KEY=file-secret-key
WINEBOX_ANTHROPIC_API_KEY=sk-ant-api-key
"""
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text(secrets_content)

        secrets = load_secrets(secrets_file)
        assert secrets.secret_key == "file-secret-key"
        assert secrets.anthropic_api_key == "sk-ant-api-key"

    def test_load_secrets_env_override(self, tmp_path):
        """Test environment variables override file secrets."""
        secrets_content = """
WINEBOX_SECRET_KEY=file-secret-key
"""
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text(secrets_content)

        with patch.dict(os.environ, {"WINEBOX_SECRET_KEY": "env-secret-key"}):
            secrets = load_secrets(secrets_file)

        assert secrets.secret_key == "env-secret-key"

    def test_load_secrets_anthropic_key_alias(self, tmp_path):
        """Test ANTHROPIC_API_KEY is also checked."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-common-name"}):
            secrets = load_secrets(tmp_path / "nonexistent.env")

        assert secrets.anthropic_api_key == "sk-common-name"


class TestSettings:
    """Test the Settings class."""

    def setup_method(self):
        """Reset settings before each test."""
        reset_settings()

    def test_settings_defaults(self):
        """Test Settings with default configuration."""
        settings = Settings()
        assert settings.app_name == "WineBox"
        assert settings.host == "127.0.0.1"
        assert settings.port == 8000
        assert settings.mongodb_url == "mongodb://localhost:27017"

    def test_settings_generates_secret_key(self):
        """Test that a secret key is generated if not provided."""
        settings = Settings()
        assert settings.secret_key is not None
        assert len(settings.secret_key) > 20

    def test_settings_uses_provided_secret_key(self, tmp_path):
        """Test that provided secret key is used."""
        secrets_content = """
WINEBOX_SECRET_KEY=my-provided-key
"""
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text(secrets_content)

        secrets = load_secrets(secrets_file)
        settings = Settings(secrets=secrets)
        assert settings.secret_key == "my-provided-key"

    def test_settings_property_accessors(self):
        """Test all property accessors work correctly."""
        config = WineboxConfig(
            app_name="TestApp",
            server=ServerConfig(host="0.0.0.0", port=9000),
            database=DatabaseConfig(mongodb_database="testdb"),
        )
        secrets = SecretsConfig(
            secret_key="test-key",
            anthropic_api_key="sk-test",
        )
        settings = Settings(config=config, secrets=secrets)

        # Test flat properties
        assert settings.app_name == "TestApp"
        assert settings.host == "0.0.0.0"
        assert settings.port == 9000
        assert settings.mongodb_database == "testdb"
        assert settings.secret_key == "test-key"
        assert settings.anthropic_api_key == "sk-test"

        # Test computed properties
        assert settings.max_upload_size_bytes == 10 * 1024 * 1024

    def test_get_settings_singleton(self):
        """Test get_settings returns same instance."""
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_settings_clears_cache(self):
        """Test reset_settings clears the cached instance."""
        reset_settings()
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2


class TestFindConfigFile:
    """Test find_config_file function."""

    def test_find_config_file_in_cwd(self, tmp_path, monkeypatch):
        """Test finding config file in current directory."""
        config_file = tmp_path / "config.toml"
        config_file.write_text("[server]\nport = 8000\n")

        monkeypatch.chdir(tmp_path)
        found = find_config_file()
        assert found == config_file

    def test_find_config_file_not_found(self, tmp_path, monkeypatch):
        """Test when no config file exists."""
        monkeypatch.chdir(tmp_path)
        found = find_config_file()
        assert found is None


class TestFindSecretsFile:
    """Test find_secrets_file function."""

    def test_find_secrets_file_in_cwd(self, tmp_path, monkeypatch):
        """Test finding secrets file in current directory."""
        secrets_file = tmp_path / "secrets.env"
        secrets_file.write_text("WINEBOX_SECRET_KEY=test\n")

        monkeypatch.chdir(tmp_path)
        found = find_secrets_file()
        assert found == secrets_file

    def test_find_secrets_file_not_found(self, tmp_path, monkeypatch):
        """Test when no secrets file exists."""
        monkeypatch.chdir(tmp_path)
        found = find_secrets_file()
        assert found is None
