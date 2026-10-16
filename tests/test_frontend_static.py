from pathlib import Path
import re


def test_frontend_selector_helpers_are_distinct():
    js = Path("app/static/app.js").read_text(encoding="utf-8")
    first_line = js.splitlines()[0]
    assert "const $=" in first_line
    assert "$$=" in first_line
    assert not re.search(r"const \\$=.*?,\\s*\\$=", first_line)


def test_frontend_asset_version_matches_backend():
    version = Path("VERSION").read_text(encoding="utf-8").strip()
    html = Path("app/templates/index.html").read_text(encoding="utf-8")
    main = Path("app/main.py").read_text(encoding="utf-8")
    assert f"/static/app.js?v={version}" in html
    assert f"/static/app.css?v={version}" in html
    assert f'version="{version}"' in main
    assert f'"version": "{version}"' in main
