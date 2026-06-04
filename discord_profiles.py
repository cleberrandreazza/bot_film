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
_HEADERS = {"User-Agent": "DiscordBot (https://github.com/cleberrandreazza/bot_film, 1.0)"}


def _bot_token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


def _guild_id() -> str:
    return os.environ.get("DISCORD_GUILD_ID", "").strip()


def _headers() -> dict:
    token = _bot_token()
    return {**_HEADERS, "Authorization": f"Bot {token}"}


def avatar_cdn_url(user_id: str, avatar: str | None) -> str:
    """URL pública do avatar no CDN do Discord."""
    if not str(user_id).isdigit():
        return "https://cdn.discordapp.com/embed/avatars/0.png"
    if avatar:
        ext = "gif" if str(avatar).startswith("a_") else "png"
        return (
            f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=64"
        )
    idx = (int(user_id) >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


def avatar_hash_from_user(user: dict, member: dict | None = None) -> str | None:
    if member:
        av = member.get("avatar")
        if av:
            return str(av)
    user_obj = member.get("user") if member else None
    if isinstance(user_obj, dict):
        av = user_obj.get("avatar")
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
    avatar = avatar_hash_from_user(user, member)
    return {
        "user_id": uid,
        "username": username,
        "display_name": display,
        "avatar": avatar,
        "avatar_url": avatar_cdn_url(uid, avatar),
    }


def buscar_perfil_usuario(user_id: str) -> dict[str, Any] | None:
    if not _bot_token() or not str(user_id).isdigit():
        return None

    gid = _guild_id()
    if gid:
        try:
            r = requests.get(
                f"{_DISCORD_API}/guilds/{gid}/members/{user_id}",
                headers=_headers(),
                timeout=10,
            )
            if r.ok:
                data = r.json()
                user = data.get("user") or data
                return perfil_from_api(user, data)
        except Exception:
            pass

    try:
        r = requests.get(
            f"{_DISCORD_API}/users/{user_id}",
            headers=_headers(),
            timeout=10,
        )
        if r.ok:
            return perfil_from_api(r.json())
    except Exception:
        pass
    return None


def enriquecer_perfis(entries: list[dict]) -> list[dict]:
    """Preenche avatar/username via API quando faltando."""
    out = []
    for e in entries:
        uid = str(e.get("user_id", ""))
        if e.get("avatar"):
            e = {**e, "avatar_url": avatar_cdn_url(uid, e.get("avatar"))}
            out.append(e)
            continue
        api = buscar_perfil_usuario(uid)
        if api:
            merged = {**e, **api}
            out.append(merged)
        else:
            out.append({
                **e,
                "avatar_url": avatar_cdn_url(uid, e.get("avatar")),
            })
    return out
