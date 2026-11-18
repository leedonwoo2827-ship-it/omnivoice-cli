from __future__ import annotations

import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .. import settings as settings_module
from .routes_api import router as api_router
from .routes_ui import router as ui_router

logger = logging.getLogger(__name__)

COOKIE = "omnivoice_token"
_LOCAL = {"127.0.0.1", "::1", "localhost", "testclient"}

_DENY_HTML = """<!doctype html><meta charset="utf-8"><title>OmniVoice TTS — 비밀번호 필요</title>
<body style="font-family:system-ui,'Malgun Gothic',sans-serif;max-width:560px;margin:80px auto;line-height:1.7">
<h2>OmniVoice TTS</h2>
<p>이 서버는 비밀번호가 있어야 쓸 수 있습니다.</p>
<p>받은 주소(끝에 <code>?token=…</code> 이 붙은 주소)로 한 번 열면 이 브라우저가 기억합니다.</p>
</body>"""


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
    app = FastAPI(
        title="OmniVoice TTS",
        version=__version__,
        description="이 PC 의 목소리(W1 …)로 음성 + 자막(SRT) — 발음 본사전 · 목소리 등록부 · HTTP API",
    )

    @app.middleware("http")
    async def token_guard(request: Request, call_next):
        """사내 공개(OMNIVOICE_TTS_TOKEN 을 정했을 때)용 문지기.

        - 이 PC(localhost)에서 여는 것은 그냥 통과.
        - 다른 PC 는 `Authorization: Bearer <비밀번호>` 헤더(프로그램) 또는
          쿠키(브라우저)가 있어야 한다. 브라우저는 `/?token=<비밀번호>` 로 한 번 열면
          쿠키를 받고, 주소창에서는 비밀번호를 지운 주소로 다시 간다.
        """
        token = settings_module.load().token
        client = request.client.host if request.client else ""
        if not token or client in _LOCAL:
            return await call_next(request)

        q = request.query_params.get("token")
        if q is not None and _same(q, token):
            url = request.url.remove_query_params("token")
            resp = RedirectResponse(url.path + (f"?{url.query}" if url.query else ""), status_code=303)
            resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=180 * 24 * 3600)
            return resp

        got = (request.headers.get("Authorization") or "").removeprefix("Bearer ").strip() \
            or request.cookies.get(COOKIE, "")
        if (got and _same(got, token)) or request.url.path.startswith("/static/"):
            return await call_next(request)

        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "비밀번호가 필요합니다 (Authorization: Bearer … 또는 /?token=… 로 연 브라우저)"},
                                status_code=401)
        return HTMLResponse(_DENY_HTML, status_code=401)

    web_dir = Path(__file__).resolve().parent.parent / "web"
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")
    app.include_router(ui_router, tags=["ui"])
    app.include_router(api_router, prefix="/api", tags=["api"])
    return app
