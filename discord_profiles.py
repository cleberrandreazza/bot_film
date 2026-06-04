"""Perfis de usuário Discord via REST API (avatar, username)."""

import os
from pathlib import Path
from typing import Any

import requests

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv:
    _root = Path(__file__).resolve().parent
    load_dotenv(_root / ".env")
    if (_root / ".env.local").exists():
        load_dotenv(_root / ".env.local")

_DISCORD_API = "https://discord.com/api/v10"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CineBotecao/1.0)"}


def _bot_token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


def _headers() -> dict:
    token = _bot_token()
    return {**_HEADERS, "Authorization": f"Bot {token}"}


def avatar_hash_from_user(user: dict, member: dict | None = None) -> str | None:
    """Hash do avatar (CDN discordapp.com/avatars/{id}/{hash}.png)."""
    if member:
        av = member.get("avatar")
        if av:
            return str(av)
    av = user.get("avatar")
    if av:
        return str(av)
    return None


def perfil_from_api(user: dict, member: dict | None = None) -> dict[str, Any]:
    uid = str(user.get("id", ""))
    username = user.get("username") or ""
    display = user.get("global_name") or username
    return {
        "user_id": uid,
        "username": username,
        "display_name": display,
        "avatar": avatar_hash_from_user(user, member),
    }


def buscar_perfil_usuario(user_id: str) -> dict[str, Any] | None:
    if not _bot_token() or not user_id.isdigit():
        return None
    try:
        r = requests.get(
            f"{_DISCORD_API}/users/{user_id}",
            headers=_headers(),
            timeout=10,
        )
        if not r.ok:
            return None
        return perfil_from_api(r.json())
    except Exception:
        return None


def enriquecer_perfis(entries: list[dict]) -> list[dict]:
    """Preenche avatar/username via API quando faltando."""
    out = []
    for e in entries:
        uid = str(e.get("user_id", ""))
        if e.get("avatar") and e.get("username"):
            out.append(e)
            continue
        api = buscar_perfil_usuario(uid)
        if api:
            out.append({**e, **{k: v for k, v in api.items() if v or k == "avatar"}})
        else:
            out.append(e)
    return out
