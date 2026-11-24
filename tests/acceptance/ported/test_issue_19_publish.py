# Ported from LF at 29e3bf3 (labs/factory-dashboard/tests/acceptance), factory#42.
# Only the four page cases; installer, nginx, snapshot and workflow cases are not ported.
"""Issue #19 page cases: no third-party URLs, CSP default-src 'self', no inline script body."""
from __future__ import annotations

import re
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[3] / "src" / "factory_tools" / "dashboard" / "static"
INDEX = COMPONENT / "index.html"


def test_page_has_no_third_party_urls():
    html = INDEX.read_text(encoding="utf-8")
    assert "fonts.googleapis" not in html and "fonts.gstatic" not in html
    assert not re.findall(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", html, re.I)


def test_page_stylesheet_has_no_third_party_urls():
    css = (COMPONENT / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r"""(?:url\(|@import)\s*["']?(?:https?:)?//""", css, re.I)


def test_page_has_csp_default_src_self():
    html = INDEX.read_text(encoding="utf-8")
    m = re.search(r"""<meta[^>]+http-equiv=["']Content-Security-Policy["'][^>]*>""", html, re.I)
    assert m, "no CSP meta"
    assert re.search(r"default-src\s+'self'", m.group(0))


def test_page_has_no_inline_script_body():
    html = INDEX.read_text(encoding="utf-8")
    scripts = list(re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I))
    assert len(scripts) >= 2, "expected the theme script and app.js as files"
    for m in scripts:
        assert "src=" in m.group(1), "script without src"
        assert m.group(2).strip() == "", "inline script body"
