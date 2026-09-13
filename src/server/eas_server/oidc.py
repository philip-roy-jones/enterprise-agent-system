"""Authorization-code sign-in with PKCE, state and nonce; no tokens in the browser."""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode, urlsplit
import httpx
import jwt
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from eas_server.security import token_hash


def install_oidc(app, security):
    settings, store = security.settings, security.store
    enabled = settings.auth_mode == "oidc" and bool(settings.oidc_authorization_url)
    if enabled and (
        not settings.oidc_token_url
        or any(
            urlsplit(u).scheme != "https" for u in (settings.oidc_authorization_url, settings.oidc_token_url)
        )
    ):
        raise ValueError("OIDC browser sign-in requires HTTPS authorization and token endpoints")
    redirect = settings.public_url.rstrip("/") + "/api/auth/callback"
    with store.db() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS oidc_pending(state TEXT PRIMARY KEY, verifier TEXT, nonce TEXT, expires REAL)"
        )

    @app.get("/api/auth/login")
    def login():
        if not enabled:
            raise HTTPException(404, "Sign-in provider is not configured")
        state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        with store.db() as db:
            db.execute("DELETE FROM oidc_pending WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT INTO oidc_pending VALUES(?,?,?,?)",
                (token_hash(state), verifier, nonce, time.time() + 300),
            )
        response = RedirectResponse(
            settings.oidc_authorization_url
            + "?"
            + urlencode(
                {
                    "client_id": settings.oidc_audience,
                    "redirect_uri": redirect,
                    "response_type": "code",
                    "scope": "openid",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            ),
            status_code=303,
        )
        response.set_cookie("eas_login", state, httponly=True, secure=True, samesite="lax", max_age=300)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/auth/callback")
    def callback(request: Request, state: str = "", code: str = ""):
        if (
            not enabled
            or not code
            or len(code) > 4096
            or not state
            or not secrets.compare_digest(state, request.cookies.get("eas_login", ""))
        ):
            raise HTTPException(401, "Sign-in could not be verified")
        with store.db() as db:
            pending = db.execute(
                "SELECT * FROM oidc_pending WHERE state=? AND expires>?", (token_hash(state), time.time())
            ).fetchone()
            db.execute("DELETE FROM oidc_pending WHERE state=?", (token_hash(state),))
        if not pending:
            raise HTTPException(401, "Sign-in expired; start again")
        try:
            payload = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": settings.oidc_audience,
                "code_verifier": pending["verifier"],
            }
            auth = (
                (settings.oidc_audience, settings.oidc_client_secret) if settings.oidc_client_secret else None
            )
            response = httpx.post(
                settings.oidc_token_url, data=payload, auth=auth, timeout=15, follow_redirects=False
            )
            response.raise_for_status()
            token = response.json()["id_token"]
            key = security.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
                options={"require": ["exp", "iat", "iss", "sub", "aud", "nonce"]},
            )
            if not secrets.compare_digest(claims["nonce"], pending["nonce"]) or (
                claims.get("azp", settings.oidc_audience) != settings.oidc_audience
            ):
                raise ValueError("ID token binding differs")
            p, session, _ = security.session(token)
        except (httpx.HTTPError, jwt.PyJWTError, ValueError, KeyError, TypeError, OSError):
            raise HTTPException(401, "Sign-in could not be verified") from None
        result = RedirectResponse("/", status_code=303)
        result.set_cookie("eas_session", session, httponly=True, secure=True, samesite="strict", max_age=3600)
        result.delete_cookie("eas_login", secure=True, httponly=True, samesite="lax")
        result.headers["Cache-Control"] = "no-store"
        return result
