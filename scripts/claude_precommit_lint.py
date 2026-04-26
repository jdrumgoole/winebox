"""Claude Code PreToolUse hook — block `git commit` when static-asset lint fails.

Wired up in .claude/settings.json under PreToolUse for the Bash tool. The
harness invokes this on every Bash call with the tool payload on stdin.
The script no-ops for any command other than `git commit`; for commits it
runs scripts/lint_static_assets.py and refuses the tool call if any rule
fires (non-zero exit code is what Claude Code uses to block).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def is_git_commit(cmd: str) -> bool:
    """Return True if ``cmd`` invokes ``git commit`` somewhere in the line.

    Matches the bare command, chained shell forms (``&& git commit``,
    ``; git commit``), and grouped forms (``( ... ) && git commit``).
    Avoids matching strings like ``git commit-tree`` or comments.
    """
    if not cmd:
        return False
    # Normalise whitespace so we can do simple token matching.
    tokens = cmd.replace("&&", " ").replace("||", " ").replace(";", " ").split()
    for i, tok in enumerate(tokens):
        if tok == "git" and i + 1 < len(tokens) and tokens[i + 1] == "commit":
            return True
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Don't block when we can't parse the payload.

    cmd = (payload.get("tool_input") or {}).get("command", "") or ""
    if not is_git_commit(cmd):
        return 0

    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            str(repo_root / "scripts" / "lint_static_assets.py"),
        ],
        cwd=repo_root,
    )
    if result.returncode != 0:
        # Surface a helpful message in the hook output so the model and the
        # user both see why the commit was refused.
        print(
            "\nstatic-asset lint refused the commit. "
            "Fix the violations above (move inline scripts/handlers to "
            "external JS files) and try again.",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
