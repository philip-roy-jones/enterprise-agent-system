"""Serve the console with asset URLs that change when their contents change."""

import hashlib
from pathlib import Path
import re

from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


class FrontendFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def console_page(directory: Path):
    html = (directory / "index.html").read_text(encoding="utf-8")

    def asset_url(match):
        asset = directory / match.group(1)
        version = hashlib.sha256(asset.read_bytes()).hexdigest()[:16]
        return f"/static/{match.group(1)}?v={version}"

    html = re.sub(r"/static/([\w-]+\.(?:js|css))", asset_url, html)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
