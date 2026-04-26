"""Static-asset lint — fails the build on patterns that break in production.

Each rule guards an actual past incident, not a stylistic preference. New
rules belong here when a regression slips past code review and we want a
mechanical check that prevents the same class of bug from re-shipping.

Run:
    uv run python scripts/lint_static_assets.py

Exits with code 0 on a clean tree, code 1 if any rule fires.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# Files outside this list are not scanned. Keep the surface small so the
# rules stay focused on user-facing static assets.
HTML_FILES: tuple[str, ...] = (
    "winebox/static/index.html",
    "winebox/static/landing.html",
    "winebox/static/design-system.html",
    "winebox/static/price-tracker.html",
)

# Regex that flags a non-empty <script> block (i.e. an inline script body),
# but allows <script src="..."> tags. Matches when <script ...> is followed
# by anything other than whitespace and an immediate </script>.
INLINE_SCRIPT_RE = re.compile(
    r"<script(?![^>]*\bsrc=)[^>]*>(?!\s*</script>)",
    re.IGNORECASE,
)

# Inline event handlers: on*="..." attributes. The leading whitespace is
# required so we don't match e.g. attribute names that happen to contain
# "on" in the middle.
INLINE_HANDLER_RE = re.compile(
    r"\son\w+\s*=\s*\"",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Violation:
    file: Path
    line: int
    rule: str
    snippet: str

    def format(self) -> str:
        return f"{self.file}:{self.line}: [{self.rule}] {self.snippet.strip()}"


def scan_file(path: Path) -> list[Violation]:
    """Return every violation found in ``path``."""
    if not path.exists():
        return []

    violations: list[Violation] = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        if INLINE_SCRIPT_RE.search(line):
            violations.append(
                Violation(
                    file=path,
                    line=line_no,
                    rule="inline-script",
                    snippet=line[:200],
                )
            )
        if INLINE_HANDLER_RE.search(line):
            violations.append(
                Violation(
                    file=path,
                    line=line_no,
                    rule="inline-handler",
                    snippet=line[:200],
                )
            )
    return violations


def scan(repo_root: Path, files: Iterable[str]) -> list[Violation]:
    """Run every rule across ``files`` and return all violations."""
    out: list[Violation] = []
    for rel in files:
        out.extend(scan_file(repo_root / rel))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root (defaults to the parent of this script).",
    )
    args = parser.parse_args()

    violations = scan(args.root, HTML_FILES)
    if not violations:
        print("static-asset lint: clean")
        return 0

    print(f"static-asset lint: {len(violations)} violation(s)\n")
    print("Why each rule exists:")
    print(
        "  inline-script   The project's CSP forbids inline <script>. "
        "Browsers silently block them, so they ship as broken features. "
        "Move the body to a /static/js/*.js file and load it with src=."
    )
    print(
        "  inline-handler  Inline on*= attributes are also CSP-blocked. "
        "Replace with addEventListener wired up from an external script."
    )
    print()
    for v in violations:
        print(v.format())
    return 1


if __name__ == "__main__":
    sys.exit(main())
