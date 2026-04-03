"""CLI for managing the WineBox admin server."""

import argparse
import os
import signal
import sys
from pathlib import Path

PID_FILE = Path("/tmp/winebox-admin.pid")


def _get_pid() -> int | None:
    """Read PID from file, return None if not running."""
    if not PID_FILE.exists():
        return None
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)  # Check if process exists
        return pid
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return None


def start(args: argparse.Namespace) -> None:
    """Start the admin server."""
    if _get_pid():
        print(f"Admin server already running (PID {_get_pid()})")
        sys.exit(1)

    import subprocess
    cmd = [
        sys.executable, "-m", "uvicorn",
        "admin_app.main:app",
        "--host", args.host,
        "--port", str(args.port),
        "--workers", str(args.workers),
    ]
    proc = subprocess.Popen(cmd, cwd=Path(__file__).parent.parent)
    PID_FILE.write_text(str(proc.pid))
    print(f"Admin server started on http://{args.host}:{args.port} (PID {proc.pid})")


def stop(args: argparse.Namespace) -> None:
    """Stop the admin server."""
    pid = _get_pid()
    if not pid:
        print("Admin server is not running")
        sys.exit(1)
    os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    print(f"Admin server stopped (PID {pid})")


def status(args: argparse.Namespace) -> None:
    """Report admin server status."""
    pid = _get_pid()
    if pid:
        print(f"Admin server is running (PID {pid})")
    else:
        print("Admin server is not running")


def restart(args: argparse.Namespace) -> None:
    """Restart the admin server."""
    pid = _get_pid()
    if pid:
        stop(args)
    start(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="WineBox Admin Server")
    sub = parser.add_subparsers(dest="command", required=True)

    start_p = sub.add_parser("start", help="Start the admin server")
    start_p.add_argument("--host", default="127.0.0.1")
    start_p.add_argument("--port", type=int, default=8001)
    start_p.add_argument("--workers", type=int, default=1)
    start_p.set_defaults(func=start)

    stop_p = sub.add_parser("stop", help="Stop the admin server")
    stop_p.set_defaults(func=stop)

    status_p = sub.add_parser("status", help="Check server status")
    status_p.set_defaults(func=status)

    restart_p = sub.add_parser("restart", help="Restart the admin server")
    restart_p.add_argument("--host", default="127.0.0.1")
    restart_p.add_argument("--port", type=int, default=8001)
    restart_p.add_argument("--workers", type=int, default=1)
    restart_p.set_defaults(func=restart)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
