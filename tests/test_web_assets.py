"""Browsers must request changed frontend assets when the console is reloaded."""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eas_server.web_assets import FrontendFiles, console_page


def test_console_versions_changed_assets_and_revalidates_cached_files(tmp_path):
    (tmp_path / "index.html").write_text(
        '<link rel="stylesheet" href="/static/style.css"><script src="/static/activity.js"></script>'
    )
    (tmp_path / "style.css").write_text("body {}")
    script = tmp_path / "activity.js"
    script.write_text("oldDropdown()")
    app = FastAPI()
    app.mount("/static", FrontendFiles(directory=tmp_path))
    app.get("/")(lambda: console_page(tmp_path))
    with TestClient(app) as client:
        page = client.get("/")
        assert page.headers["cache-control"] == "no-store"
        old_url = re.search(r'src="([^"]+)"', page.text).group(1)
        css_url = re.search(r'href="([^"]+)"', page.text).group(1)
        assert "?v=" in old_url and "?v=" in css_url
        old = client.get(old_url)
        assert old.text == "oldDropdown()"
        assert old.headers["cache-control"] == "no-cache"
        cached = client.get(old_url, headers={"If-None-Match": old.headers["etag"]})
        assert cached.status_code == 304
        assert cached.headers["cache-control"] == "no-cache"
        script.write_text("showDetailsImmediately()")
        updated_page = client.get("/")
        new_url = re.search(r'src="([^"]+)"', updated_page.text).group(1)
        assert new_url != old_url
        assert re.search(r'href="([^"]+)"', updated_page.text).group(1) == css_url
        updated = client.get(new_url)
        assert updated.status_code == 200
        assert updated.text == "showDetailsImmediately()"
