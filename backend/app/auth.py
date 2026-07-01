"""Autenticación de alumnos por Google (OAuth 2.0) + sesiones + credenciales de Calendar.

Flujo (Authorization Code, sin librerías nuevas: httpx + google-auth):
  /auth/login     → redirige a Google (scopes: identidad + Calendar del usuario).
  /auth/callback  → canjea el código, lee el perfil, guarda el usuario (con su refresh_token
                    para Calendar), crea una SESIÓN en BD y deja una cookie httpOnly.
  /auth/me        → quién es el usuario actual (por la cookie) o 401.
  /auth/logout    → cierra la sesión.

Decisiones (MVP comercial):
- Sesión = token opaco aleatorio guardado en `sesiones_auth` (no JWT, sin dependencias extra).
- El `refresh_token` del usuario se guarda para crear eventos en SU Google Calendar (paso 4).
  Pedimos `prompt=consent` + `access_type=offline` para recibirlo siempre.
- Identidad = el email de Google (es el `user_id` real, sustituye al user_id que mandaba el cliente).
"""
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google.oauth2.credentials import Credentials
from loguru import logger
from sqlalchemy import text

from .config import settings
from .db import engine

router = APIRouter(prefix="/auth", tags=["auth"])

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
# Mínimo necesario: identidad + crear eventos en el Calendar del propio usuario.
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/calendar.events",
]
COOKIE = "faro_sid"
STATE_COOKIE = "faro_oauth_state"
SESSION_TTL_DIAS = 30
_SECURE = settings.oauth_redirect_uri.startswith("https")


_DDL = [
    """
    CREATE TABLE IF NOT EXISTS usuarios (
        email          TEXT PRIMARY KEY,
        nombre         TEXT,
        refresh_token  TEXT,
        scopes         TEXT,
        creado_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        actualizado_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sesiones_auth (
        sid       TEXT PRIMARY KEY,
        email     TEXT NOT NULL REFERENCES usuarios(email) ON DELETE CASCADE,
        creado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expira_at TIMESTAMPTZ NOT NULL
    )
    """,
]


async def crear_tablas_auth() -> None:
    """Crea las tablas de auth (idempotente). Se llama en el startup."""
    async with engine.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))


def _configurado() -> bool:
    return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)


# --------------------------------------------------------------------------- #
# Sesiones + usuarios
# --------------------------------------------------------------------------- #
async def _upsert_usuario(email: str, nombre: str | None, refresh_token: str | None) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO usuarios (email, nombre, refresh_token, scopes) "
                "VALUES (:email, :nombre, :rt, :scopes) "
                "ON CONFLICT (email) DO UPDATE SET "
                "  nombre = EXCLUDED.nombre, "
                # No pisar el refresh_token con NULL si Google no lo reenvía esta vez.
                "  refresh_token = COALESCE(EXCLUDED.refresh_token, usuarios.refresh_token), "
                "  scopes = EXCLUDED.scopes, actualizado_at = now()"
            ),
            {"email": email, "nombre": nombre, "rt": refresh_token, "scopes": " ".join(SCOPES)},
        )


async def _crear_sesion(email: str) -> str:
    sid = secrets.token_urlsafe(32)
    expira = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DIAS)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO sesiones_auth (sid, email, expira_at) VALUES (:sid, :email, :exp)"),
            {"sid": sid, "email": email, "exp": expira},
        )
    return sid


async def usuario_por_sid(sid: str | None) -> dict | None:
    """Devuelve {email, nombre} de una sesión vigente, o None."""
    if not sid:
        return None
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT u.email, u.nombre FROM sesiones_auth s "
                    "JOIN usuarios u ON u.email = s.email "
                    "WHERE s.sid = :sid AND s.expira_at > now()"
                ),
                {"sid": sid},
            )
        ).mappings().first()
    return dict(row) if row else None


async def usuario_actual(request: Request) -> dict | None:
    """Usuario logueado a partir de la cookie de sesión (para endpoints HTTP)."""
    return await usuario_por_sid(request.cookies.get(COOKIE))


async def credenciales_calendar(email: str) -> Credentials | None:
    """Credenciales OAuth del usuario para su Google Calendar (a partir del refresh_token
    guardado). google-auth refresca el access_token solo cuando hace falta. None si no hay token."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT refresh_token FROM usuarios WHERE email = :email"),
                {"email": email},
            )
        ).mappings().first()
    if not row or not row["refresh_token"]:
        return None
    # OJO: NO pasar `scopes` aquí. Al refrescar, google-auth enviaría el scope (incluido
    # `openid`) y Google responde `invalid_scope`. Sin scopes hereda los ya concedidos
    # (incl. calendar.events), que es justo lo que queremos.
    return Credentials(
        token=None,
        refresh_token=row["refresh_token"],
        token_uri=TOKEN_URL,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
    )


# --------------------------------------------------------------------------- #
# Endpoints OAuth
# --------------------------------------------------------------------------- #
@router.get("/login")
async def login():
    if not _configurado():
        return JSONResponse({"error": "OAuth no configurado (faltan client_id/secret)"}, status_code=503)
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    url = AUTHORIZE_URL + "?" + httpx.QueryParams(params).__str__()
    resp = RedirectResponse(url, status_code=302)
    # Cookie de estado (CSRF), corta vida; se valida en el callback.
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True,
                    samesite="lax", secure=_SECURE)
    return resp


@router.get("/callback")
async def callback(request: Request):
    if not _configurado():
        return JSONResponse({"error": "OAuth no configurado"}, status_code=503)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code:
        return JSONResponse({"error": request.query_params.get("error", "sin código")}, status_code=400)
    if not state or state != request.cookies.get(STATE_COOKIE):
        return JSONResponse({"error": "state inválido (posible CSRF)"}, status_code=400)

    async with httpx.AsyncClient(timeout=20) as cli:
        tok = await cli.post(TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "redirect_uri": settings.oauth_redirect_uri,
            "grant_type": "authorization_code",
        })
        if tok.status_code != 200:
            logger.error(f"[auth] canje de código falló: {tok.status_code} {tok.text[:300]}")
            return JSONResponse({"error": "no pude canjear el código"}, status_code=400)
        td = tok.json()
        access_token = td.get("access_token")
        refresh_token = td.get("refresh_token")  # presente con prompt=consent
        info = await cli.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        if info.status_code != 200:
            logger.error(f"[auth] userinfo falló: {info.status_code}")
            return JSONResponse({"error": "no pude leer el perfil"}, status_code=400)
        perfil = info.json()

    email = (perfil.get("email") or "").strip().lower()
    if not email:
        return JSONResponse({"error": "Google no devolvió email"}, status_code=400)
    await _upsert_usuario(email, perfil.get("name"), refresh_token)
    sid = await _crear_sesion(email)
    logger.info(f"[auth] login OK email={email} refresh_token={'sí' if refresh_token else 'no'}")

    resp = RedirectResponse(settings.post_login_redirect, status_code=302)
    resp.set_cookie(COOKIE, sid, max_age=SESSION_TTL_DIAS * 86400, httponly=True,
                    samesite="lax", secure=_SECURE)
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.get("/me")
async def me(request: Request):
    u = await usuario_actual(request)
    if not u:
        # `configurado` le dice al front si debe hacer de PUERTA (redirigir a login) o degradar al
        # uso local (dev sin credenciales OAuth). Ver authUI() en static/4g/index.html.
        return JSONResponse({"autenticado": False, "configurado": _configurado()}, status_code=401)
    return {"autenticado": True, "email": u["email"], "nombre": u.get("nombre")}


@router.post("/logout")
async def logout(request: Request):
    sid = request.cookies.get(COOKIE)
    if sid:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM sesiones_auth WHERE sid = :sid"), {"sid": sid})
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp
