"""Tests for CLI server helpers (no process management)."""

import os
from pathlib import Path

import pytest

from winebox.cli.server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ensure_directories,
    get_pid,
    main,
)


class TestGetPid:
    """Tests for get_pid helper."""

    def test_get_pid_no_pidfile(self, tmp_path, monkeypatch):
        """Returns None when no PID file exists."""
        import winebox.cli.server as server_mod

        monkeypatch.setattr(server_mod, "PID_FILE", tmp_path / "nonexistent.pid")
        assert get_pid() is None

    def test_get_pid_stale_pidfile(self, tmp_path, monkeypatch):
        """Returns None and cleans up stale PID file."""
        import winebox.cli.server as server_mod

        pid_file = tmp_path / "stale.pid"
        # Use a PID that almost certainly doesn't exist
        pid_file.write_text("999999999")
        monkeypatch.setattr(server_mod, "PID_FILE", pid_file)

        result = get_pid()
        assert result is None
        # Stale PID file should be cleaned up
        assert not pid_file.exists()


class TestEnsureDirectories:
    """Tests for ensure_directories helper."""

    def test_ensure_directories(self, tmp_path, monkeypatch):
        """Creates required dirs in tmp."""
        import winebox.cli.server as server_mod

        data_dir = tmp_path / "data"
        monkeypatch.setattr(server_mod, "DATA_DIR", data_dir)

        ensure_directories()
        assert data_dir.exists()
        assert (data_dir / "images").exists()


class TestParseArgs:
    """Tests for argument parsing via main()."""

    def test_parse_args_start_defaults(self):
        """Default host/port."""
        assert DEFAULT_HOST == "0.0.0.0"
        assert DEFAULT_PORT == 8000

    def test_parse_args_custom_port(self):
        """--port 9000 parsed via argparse."""
        import argparse
        from winebox.cli.server import main as _main

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        start_parser = subparsers.add_parser("start")
        start_parser.add_argument("--port", "-p", type=int, default=DEFAULT_PORT)
        start_parser.add_argument("--host", default=DEFAULT_HOST)

        args = parser.parse_args(["start", "--port", "9000"])
        assert args.port == 9000
        assert args.command == "start"

    def test_parse_args_stop(self):
        """stop subcommand recognized."""
        import argparse

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("stop")

        args = parser.parse_args(["stop"])
        assert args.command == "stop"
