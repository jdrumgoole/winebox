"""WineBox server control script.

Usage:
    winebox-server start [--port PORT] [--reload]
    winebox-server stop
    winebox-server restart [--port PORT]
    winebox-server status
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


# Configuration
DATA_DIR = Path("data")
PID_FILE = DATA_DIR / "winebox.pid"
LOG_FILE = DATA_DIR / "winebox.log"
DEFAULT_PORT = 8000
DEFAULT_HOST = "0.0.0.0"


def ensure_directories() -> None:
    """Ensure required directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "images").mkdir(parents=True, exist_ok=True)


def get_pid() -> int | None:
    """Get the PID of the running server, if any."""
    if not PID_FILE.exists():
        return None

    try:
        pid = int(PID_FILE.read_text().strip())
        # Check if process is actually running
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError):
        # PID file exists but process is not running
        PID_FILE.unlink(missing_ok=True)
        return None


def find_running_server() -> int | None:
    """Find any running winebox uvicorn process."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn winebox.main:app"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Return first PID found
            return int(result.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def start_server(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST,
                 reload: bool = False, foreground: bool = False) -> bool:
    """Start the WineBox server.

    Args:
        port: Port to bind to
        host: Host to bind to
        reload: Enable auto-reload for development
        foreground: Run in foreground (blocking)

    Returns:
        True if server started successfully
    """
    # Check if already running
    pid = get_pid() or find_running_server()
    if pid:
        print(f"Server is already running (PID: {pid})")
        return False

    ensure_directories()

    cmd = [
        sys.executable, "-m", "uvicorn",
        "winebox.main:app",
        "--host", host,
        "--port", str(port),
    ]

    if reload:
        cmd.append("--reload")

    print(f"Starting WineBox server on http://{host}:{port}")

    if foreground:
        print("Press Ctrl+C to stop the server")
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            print("\nServer stopped")
        return True

    # Start in background
    with open(LOG_FILE, "w") as log:
        process = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    # Wait a moment and check if it started
    time.sleep(1)
    if process.poll() is None:
        PID_FILE.write_text(str(process.pid))
        print(f"Server started with PID: {process.pid}")
        print(f"Logs available at: {LOG_FILE}")
        return True
    else:
        print("Failed to start server. Check logs for details.")
        return False


def stop_server() -> bool:
    """Stop the WineBox server.

    Returns:
        True if server was stopped
    """
    pid = get_pid()

    if not pid:
        # Try to find running server anyway
        pid = find_running_server()

    if not pid:
        print("Server is not running")
        return False

    print(f"Stopping server (PID: {pid})...")

    try:
        # Send SIGTERM for graceful shutdown
        os.kill(pid, signal.SIGTERM)

        # Wait for process to terminate
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
        else:
            # Process didn't stop, send SIGKILL
            print("Server didn't stop gracefully, forcing...")
            os.kill(pid, signal.SIGKILL)

        print("Server stopped")
        PID_FILE.unlink(missing_ok=True)
        return True

    except ProcessLookupError:
        print("Server was not running")
        PID_FILE.unlink(missing_ok=True)
        return False
    except PermissionError:
        print(f"Permission denied to stop process {pid}")
        return False


def restart_server(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST) -> bool:
    """Restart the WineBox server.

    Args:
        port: Port to bind to
        host: Host to bind to

    Returns:
        True if server restarted successfully
    """
    print("Restarting WineBox server...")
    stop_server()
    time.sleep(1)
    return start_server(port=port, host=host)


def server_status() -> None:
    """Print the server status."""
    pid = get_pid()

    if not pid:
        pid = find_running_server()

    if pid:
        print(f"WineBox server is running (PID: {pid})")

        # Try to get health status
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as response:
                import json
                data = json.loads(response.read().decode())
                print(f"  Status: {data.get('status', 'unknown')}")
                print(f"  Version: {data.get('version', 'unknown')}")
        except Exception:
            print("  (Could not fetch health status)")
    else:
        print("WineBox server is not running")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="WineBox server control script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s start                  Start server on default port (8000)
  %(prog)s start --port 8080      Start server on port 8080
  %(prog)s start --reload         Start with auto-reload for development
  %(prog)s start --foreground     Start in foreground (blocking)
  %(prog)s stop                   Stop the server
  %(prog)s restart                Restart the server
  %(prog)s status                 Check server status
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start the server")
    start_parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind to (default: {DEFAULT_PORT})",
    )
    start_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST})",
    )
    start_parser.add_argument(
        "--reload", "-r",
        action="store_true",
        help="Enable auto-reload for development",
    )
    start_parser.add_argument(
        "--foreground", "-f",
        action="store_true",
        help="Run in foreground (blocking)",
    )

    # Stop command
    subparsers.add_parser("stop", help="Stop the server")

    # Restart command
    restart_parser = subparsers.add_parser("restart", help="Restart the server")
    restart_parser.add_argument(
        "--port", "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind to (default: {DEFAULT_PORT})",
    )
    restart_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST})",
    )

    # Status command
    subparsers.add_parser("status", help="Check server status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "start":
            success = start_server(
                port=args.port,
                host=args.host,
                reload=args.reload,
                foreground=args.foreground,
            )
            return 0 if success else 1

        elif args.command == "stop":
            success = stop_server()
            return 0 if success else 1

        elif args.command == "restart":
            success = restart_server(port=args.port, host=args.host)
            return 0 if success else 1

        elif args.command == "status":
            server_status()
            return 0

    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130

    return 0


if __name__ == "__main__":
    sys.exit(main())
