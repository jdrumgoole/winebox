"""Repair the GitHub Actions self-hosted runner on the OAT droplet.

Background
----------
A nightly workflow cleanup step deleted
``/opt/github-runner/externals.<version>/`` directories on the
assumption they were superseded leftovers from runner self-updates.
The actions-runner installer puts shared binaries (notably
``externals/node20/bin/node``, used by every JavaScript action) under
a versioned directory and exposes them through a canonical
``externals/`` path. Removing one of the versioned dirs leaves the
canonical path pointing at deleted inodes; the next workflow run
crashes at the first JS action with::

    An error occurred trying to start process
    '/opt/github-runner/externals/node20/bin/node' ...
    No such file or directory

What this script does
---------------------
1. SSHes to the OAT droplet as root.
2. Detects the runner version actually installed (newest surviving
   ``externals.<v>`` directory).
3. Stops the runner ``systemd`` unit so we don't fight a live agent.
4. Downloads the matching runner tarball from
   ``github.com/actions/runner/releases``.
5. Re-extracts ONLY the ``externals/`` tree over the broken one.
   Everything else (``.runner`` registration, ``.credentials``,
   ``_work/``, ``bin/``, ``run.sh``) is preserved.
6. Restarts the service and confirms it's active.

Usage
-----
::

    uv run python scripts/repair_oat_runner.py             # dry-run; prints the commands it WOULD send
    uv run python scripts/repair_oat_runner.py --confirm   # actually run them

Or via invoke::

    invoke oat-repair-runner            # dry-run
    invoke oat-repair-runner --confirm
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# The OAT droplet's static IP. Matches CLAUDE.md and the existing
# deploy/oat-status / deploy-oat invoke tasks.
OAT_HOST = "root@46.101.134.8"


# The remote script is composed locally and piped to ``ssh ... bash -s``
# so the whole repair runs atomically (no per-command round-trip). The
# heredoc-style quoting in argparse makes Python-side templating
# brittle, so the script is kept literal here.
REMOTE_SCRIPT = r"""
set -euo pipefail
cd /opt/github-runner

# 1. Detect the installed runner version. The newest surviving
#    `externals.<version>/` directory is the canonical reference; if
#    they were all wiped this script can't help.
VERSION=$(ls -d externals.* 2>/dev/null | sort -V | tail -1 | sed 's/^externals\.//')
if [ -z "$VERSION" ]; then
    echo "ERROR: no externals.<version>/ dirs found under /opt/github-runner." >&2
    echo "       The runner agent itself probably needs a full reinstall." >&2
    exit 1
fi
echo "Detected runner version: $VERSION"

# 2. Find and stop the runner systemd unit so we don't fight a live
#    agent for the externals/ tree.
SERVICE=$(systemctl list-units --type=service --no-legend 'actions.runner.*' \
    | awk '{print $1}' | head -1)
if [ -n "$SERVICE" ]; then
    echo "Stopping $SERVICE"
    systemctl stop "$SERVICE"
else
    echo "WARN: no actions.runner.* service found — skipping stop." >&2
fi

# 3. Re-extract externals/ from the matching tarball.
TARBALL=$(mktemp -t actions-runner-XXXX.tar.gz)
URL="https://github.com/actions/runner/releases/download/v${VERSION}/actions-runner-linux-x64-${VERSION}.tar.gz"
echo "Downloading $URL"
curl -fsSL -o "$TARBALL" "$URL"

# Tarball layout: ./externals/...  ./bin/...  ./run.sh ...
# Only extract externals/; leave bin/, run.sh, .runner, .credentials,
# _work/ alone. Wipe the existing externals/ first because we don't
# know whether the path is a directory, symlink, or partial tree.
rm -rf /opt/github-runner/externals
tar xzf "$TARBALL" -C /opt/github-runner ./externals
rm -f "$TARBALL"
echo "externals/ re-extracted."

# 4. Restart the runner and confirm.
if [ -n "$SERVICE" ]; then
    echo "Starting $SERVICE"
    systemctl start "$SERVICE"
    if systemctl is-active --quiet "$SERVICE"; then
        echo "$SERVICE is active."
    else
        echo "ERROR: $SERVICE did not come up. Last 20 log lines:" >&2
        journalctl -u "$SERVICE" -n 20 --no-pager >&2
        exit 1
    fi
fi

echo "Repair complete."
ls /opt/github-runner/externals/ | head
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually send the repair commands. Without this flag, dry-runs and prints what would be sent.",
    )
    parser.add_argument(
        "--host",
        default=OAT_HOST,
        help=f"SSH target. Default: {OAT_HOST}",
    )
    args = parser.parse_args()

    if not args.confirm:
        print("=== DRY RUN ===")
        print(f"Would SSH to: {args.host}")
        print("Would pipe the following script to `bash -s`:")
        print("---")
        print(REMOTE_SCRIPT.strip())
        print("---")
        print("Re-run with --confirm to execute.")
        return 0

    print(f"Connecting to {args.host} ...")
    cmd = ["ssh", "-o", "BatchMode=yes", args.host, "bash -s"]
    result = subprocess.run(cmd, input=REMOTE_SCRIPT, text=True)
    if result.returncode != 0:
        print(f"\nRepair exited with status {result.returncode}.", file=sys.stderr)
        return result.returncode
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
