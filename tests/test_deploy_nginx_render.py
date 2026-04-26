"""Tests for the nginx admin-allowlist renderer in deploy.common."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from deploy import common
from deploy.common import (
    ADMIN_ALLOWLIST_PLACEHOLDER,
    render_nginx_config,
)


@pytest.fixture()
def fake_allowlist(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the renderer to a tmp `winebox-admin.toml`.

    The production renderer reads `deploy/winebox-admin.toml` (resolved via
    `Path(__file__).parent`). Tests should not depend on the real file —
    operators may legitimately edit it.
    """
    cfg = tmp_path / "winebox-admin.toml"
    cfg.write_text(
        "[oat]\nallow = ['1.2.3.4', '10.0.0.0/8']\n"
        "[empty]\nallow = []\n"
    )

    def _patched_loader(section: str) -> list[str]:
        with cfg.open("rb") as fh:
            data = tomllib.load(fh)
        entries = data.get(section, {}).get("allow") or []
        if not entries:
            raise ValueError(
                f"deploy/winebox-admin.toml has no '[{section}].allow' entries"
            )
        return entries

    monkeypatch.setattr(common, "_load_admin_allowlist", _patched_loader)
    return cfg


def _make_template(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "site.conf"
    p.write_text(body)
    return p


def test_substitutes_at_location_indent(
    tmp_path: Path, fake_allowlist: Path
) -> None:
    template = _make_template(
        tmp_path,
        "server {\n"
        "    location /admin {\n"
        "        # __ADMIN_ALLOWLIST__\n"
        "        proxy_pass http://app;\n"
        "    }\n"
        "}\n",
    )
    rendered = render_nginx_config(template, "oat").read_text()

    assert "        allow 1.2.3.4;" in rendered
    assert "        allow 10.0.0.0/8;" in rendered
    assert "        deny all;" in rendered
    assert "# __ADMIN_ALLOWLIST__" not in rendered


def test_each_placeholder_takes_its_own_indent(
    tmp_path: Path, fake_allowlist: Path
) -> None:
    template = _make_template(
        tmp_path,
        "server {\n"
        "    # __ADMIN_ALLOWLIST__\n"
        "    location /admin {\n"
        "        # __ADMIN_ALLOWLIST__\n"
        "    }\n"
        "}\n",
    )
    rendered = render_nginx_config(template, "oat").read_text()

    assert "    allow 1.2.3.4;" in rendered           # server-level
    assert "        allow 1.2.3.4;" in rendered       # location-level
    assert rendered.count("allow 1.2.3.4;") == 2
    assert rendered.count("allow 10.0.0.0/8;") == 2
    assert rendered.count("deny all;") == 2


def test_placeholder_in_prose_comment_is_left_alone(
    tmp_path: Path, fake_allowlist: Path
) -> None:
    template = _make_template(
        tmp_path,
        "# Every `# __ADMIN_ALLOWLIST__` placeholder below is rendered.\n"
        "server {\n"
        "    # __ADMIN_ALLOWLIST__\n"
        "}\n",
    )
    rendered = render_nginx_config(template, "oat").read_text()

    assert "# Every `# __ADMIN_ALLOWLIST__` placeholder below" in rendered
    assert "    allow 1.2.3.4;" in rendered


def test_template_without_standalone_placeholder_raises(
    tmp_path: Path, fake_allowlist: Path
) -> None:
    template = _make_template(
        tmp_path,
        "# Doc mentions __ADMIN_ALLOWLIST__ but has no placeholder line.\n"
        "server { }\n",
    )
    with pytest.raises(ValueError, match="no standalone"):
        render_nginx_config(template, "oat")


def test_empty_allowlist_section_raises(
    tmp_path: Path, fake_allowlist: Path
) -> None:
    template = _make_template(
        tmp_path,
        "server {\n    # __ADMIN_ALLOWLIST__\n}\n",
    )
    with pytest.raises(ValueError, match=r"\[empty\]\.allow"):
        render_nginx_config(template, "empty")


def test_real_oat_config_renders_cleanly() -> None:
    """The committed `deploy/nginx-winebox-oat.conf` must render against the
    real `deploy/winebox-admin.toml` — catches drift if either is edited.
    Uses the real loader, not the fixture."""
    repo = Path(__file__).parent.parent
    template = repo / "deploy" / "nginx-winebox-oat.conf"
    rendered = render_nginx_config(template, "oat").read_text()

    for line in rendered.splitlines():
        assert line.strip() != ADMIN_ALLOWLIST_PLACEHOLDER, line

    # Both placeholders rendered: location-level (8-space) + server-level (4-space).
    assert "        deny all;" in rendered
    assert "    deny all;" in rendered
