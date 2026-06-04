"""Verificação de membro/role Cinéfilo no servidor Discord."""

import os
import time

import requests

_DISCORD_API = "https://discord.com/api/v10"
_CACHE: dict[str, tuple[bool, float]] = {}
_CACHE_TTL = 600
_HTTP_HEADERS = {"User-Agent": "DiscordBot (https://github.com/cleberrandreazza/bot_film, 1.0)"}


def _bot_token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


def guild_id() -> str:
    return os.environ.get("DISCORD_GUILD_ID", "").strip()


def cinefilo_role_id() -> str:
    raw = os.environ.get(
        "EVENTO_CINEFILO_ROLE_ID",
        os.environ.get("EVENTO_NOTIFY_ROLE_ID", "1508308918353526814"),
    )
    return str(raw).strip()


def _tem_role(roles: list, role_id: str) -> bool:
    return role_id in [str(x) for x in roles]


def _checar_via_oauth(access_token: str, role_id: str, gid: str) -> bool | None:
    """Usa o token do usuário logado (scope guilds.members.read)."""
    try:
        r = requests.get(
            f"{_DISCORD_API}/users/@me/guilds/{gid}/member",
            headers={
                **_HTTP_HEADERS,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=10,
        )
        if r.status_code == 404:
            return False
        if r.ok:
            return _tem_role(r.json().get("roles") or [], role_id)
        if r.status_code in (401, 403):
            print(f"[Discord] OAuth member: HTTP {r.status_code} — faça login de novo.")
            return None
    except Exception as e:
        print(f"[Discord] OAuth member: {e}")
    return None


def _checar_via_bot(user_id: str, role_id: str, gid: str, token: str) -> bool | None:
    """Fallback: API do bot (exige Server Members Intent no portal)."""
    try:
        r = requests.get(
            f"{_DISCORD_API}/guilds/{gid}/members/{user_id}",
            headers={**_HTTP_HEADERS, "Authorization": f"Bot {token}"},
            timeout=10,
        )
        if r.status_code == 404:
            return False
        if r.ok:
            return _tem_role(r.json().get("roles") or [], role_id)
        if r.status_code == 403:
            print(
                "[Discord] Bot sem acesso ao membro (ative Server Members Intent "
                "ou refaça login no site)."
            )
            return None
    except Exception as e:
        print(f"[Discord] Bot member: {e}")
    return None


def usuario_e_cinefilo(user_id: str, access_token: str | None = None) -> bool:
    """True se o usuário está no servidor e tem a role Cinéfilo."""
    user_id = (user_id or "").strip()
    gid = guild_id()
    role_id = cinefilo_role_id()
    token = (access_token or "").strip()
    bot = _bot_token()

    if not user_id or not gid or not role_id:
        return False
    if not token and not bot:
        return False

    cache_key = f"{user_id}:{hash(token) & 0xFFFF}" if token else user_id
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]

    ok = False
    if token:
        oauth = _checar_via_oauth(token, role_id, gid)
        if oauth is not None:
            ok = oauth
        elif bot:
            bot_res = _checar_via_bot(user_id, role_id, gid, bot)
            ok = bot_res if bot_res is not None else False
    elif bot:
        bot_res = _checar_via_bot(user_id, role_id, gid, bot)
        ok = bot_res if bot_res is not None else False

    _CACHE[cache_key] = (ok, now)
    return ok


def invalidar_cache_usuario(user_id: str) -> None:
    uid = (user_id or "").strip()
    keys = [k for k in _CACHE if k == uid or k.startswith(f"{uid}:")]
    for k in keys:
        _CACHE.pop(k, None)
