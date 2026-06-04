"""Camada de acesso ao banco via Convex.

Substitui o SQLite local. O bot (discord.py) e o site (Flask) chamam estas
funcoes; elas conversam com o deployment Convex via HTTP usando CONVEX_URL.

As funcoes aqui sao sincronas. No bot (codigo async) envolva as chamadas em
`asyncio.to_thread(...)` para nao travar o event loop.
"""

import os
import threading

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()
    # Convex dev grava a URL em .env.local
    if os.path.exists(".env.local"):
        load_dotenv(".env.local")

from convex import ConvexClient

_client: "ConvexClient | None" = None
_lock = threading.Lock()


def _resolve_convex_url() -> str:
    url = (os.environ.get("CONVEX_URL") or "").strip()
    if url:
        return url
    raise RuntimeError(
        "CONVEX_URL nao definido. Rode `npx convex dev` e defina CONVEX_URL "
        "(ex.: https://seu-deploy.convex.cloud) no .env / Railway."
    )


def client() -> ConvexClient:
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                _client = ConvexClient(_resolve_convex_url())
    return _client


def _clean(d: dict) -> dict:
    """Remove chaves com valor None (Convex v.optional nao aceita null)."""
    return {k: v for k, v in d.items() if v is not None}


def _q(name: str, args: dict | None = None):
    return client().query(name, args or {})


def _m(name: str, args: dict | None = None):
    return client().mutation(name, args or {})


# ───────────────────────────── listas ──

def get_status_by_filme(filme_id: str) -> str | None:
    row = _q("listas:getByFilme", {"filme_id": filme_id})
    return row["status"] if row else None


def get_titulo_by_filme(filme_id: str) -> str | None:
    return _q("listas:getTituloByFilme", {"filme_id": filme_id})


def get_adicionado_por(filme_id: str) -> dict | None:
    return _q("listas:getAdicionadoPor", {"filme_id": filme_id})


def add_filme(
    user_id: str,
    filme_id: str,
    titulo: str,
    status: str = "watchlist",
    *,
    username: str | None = None,
    display_name: str | None = None,
    avatar: str | None = None,
) -> dict:
    return _m("listas:addFilme", _clean({
        "user_id": user_id, "filme_id": filme_id,
        "titulo": titulo, "status": status,
        "username": username,
        "display_name": display_name,
        "avatar": avatar,
    }))


def set_status(filme_id: str, status: str) -> int:
    return _m("listas:setStatus", {"filme_id": filme_id, "status": status})


def marcar_assistido(
    user_id: str,
    filme_id: str,
    titulo: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    avatar: str | None = None,
    source: str | None = None,
) -> dict:
    return _m("listas:marcarAssistido", _clean({
        "user_id": user_id, "filme_id": filme_id, "titulo": titulo,
        "username": username,
        "display_name": display_name,
        "avatar": avatar,
        "source": source,
    }))


def adicionar_fila(
    user_id: str,
    filme_id: str,
    titulo: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
    avatar: str | None = None,
) -> dict:
    return _m("listas:adicionarFila", _clean({
        "user_id": user_id, "filme_id": filme_id, "titulo": titulo,
        "username": username,
        "display_name": display_name,
        "avatar": avatar,
    }))


def remove_by_filme(filme_id: str) -> int:
    return _m("listas:removeByFilme", {"filme_id": filme_id})


def remove_by_filme_status(filme_id: str, status: str) -> int:
    return _m("listas:removeByFilmeAndStatus", {"filme_id": filme_id, "status": status})


def _search_listas(titulo: str, status: str | None = None, limit: int = 50) -> list[dict]:
    args = {"titulo": titulo, "limit": limit}
    if status:
        args["status"] = status
    return _q("listas:searchByTitulo", args) or []


def search_watchlist_by_titulo(titulo: str) -> dict | None:
    rows = _search_listas(titulo, status="watchlist", limit=1)
    return rows[0] if rows else None


def search_any_by_titulo(titulo: str) -> dict | None:
    rows = _search_listas(titulo, limit=1)
    return rows[0] if rows else None


def search_titulos(titulo: str, limit: int = 8) -> list[str]:
    rows = _search_listas(titulo, limit=limit)
    return [r["titulo"] for r in rows]


def list_titulos_by_status(status: str) -> list[str]:
    rows = _q("listas:listByStatus", {"status": status}) or []
    return [r["titulo"] for r in rows]


def list_by_status(status: str) -> list[dict]:
    return _q("listas:listByStatus", {"status": status}) or []


def list_by_status_paginated(status: str, limit: int, offset: int) -> tuple[list[dict], int]:
    res = _q("listas:listByStatusPaginated", {
        "status": status, "limit": limit, "offset": offset,
    }) or {"rows": [], "total": 0}
    return res.get("rows", []), int(res.get("total", 0) or 0)


def list_watchlist_filmes() -> list[tuple[str, str]]:
    rows = _q("listas:listWatchlistFilmes", {}) or []
    return [(r["filme_id"], r["titulo"]) for r in rows]


def distinct_filme_ids() -> set[str]:
    return set(_q("listas:distinctFilmeIds", {}) or [])


def filme_ids_by_status(status: str) -> list[str]:
    return _q("listas:filmeIdsByStatus", {"status": status}) or []


# ───────────────────────────── eventos ──

def criar_evento(discord_event_id: str, filme_id: str, titulo: str,
                 data_evento: str, canal_id: str | None = None,
                 guild_id: str | None = None) -> dict:
    return _m("eventos:create", _clean({
        "discord_event_id": discord_event_id,
        "filme_id": filme_id,
        "titulo": titulo,
        "data_evento": data_evento,
        "canal_id": canal_id,
        "guild_id": guild_id,
    }))


def get_evento_by_discord(discord_event_id: str) -> dict | None:
    return _q("eventos:getByDiscordEvent", {"discord_event_id": str(discord_event_id)})


def get_evento_ativo_by_titulo(titulo: str) -> dict | None:
    return _q("eventos:getAtivoByTitulo", {"titulo": titulo})


def get_evento_ativo_by_canal(canal_id: str) -> dict | None:
    return _q("eventos:getAtivoByCanal", {"canal_id": str(canal_id)})


def filme_ids_com_evento_ativo() -> set[str]:
    """Filmes com evento Discord agendado ou ativo (não entram no sorteio)."""
    ids = _q("eventos:filmeIdsComEventoAtivo", {}) or []
    return set(ids)


def list_eventos_ativos(titulo: str | None = None, limit: int = 8) -> list[dict]:
    args = {"limit": limit}
    if titulo:
        args["titulo"] = titulo
    return _q("eventos:listAtivos", args) or []


def set_evento_status(discord_event_id: str, status: str) -> bool:
    return _m("eventos:setStatusByDiscordEvent", {
        "discord_event_id": str(discord_event_id), "status": status,
    })


# ───────────────────────────── participantes ──

def upsert_participante(discord_event_id: str, user_id: str, username: str, **flags) -> str:
    args = {
        "discord_event_id": str(discord_event_id),
        "user_id": str(user_id),
        "username": username,
    }
    if "interessado" in flags:
        args["interessado"] = int(flags["interessado"])
    if "entrou_canal" in flags:
        args["entrou_canal"] = int(flags["entrou_canal"])
    return _m("participantes:upsert", args)


def list_entrou(discord_event_id: str) -> list[dict]:
    return _q("participantes:listEntrouByEvento", {
        "discord_event_id": str(discord_event_id),
    }) or []


def list_participantes_evento(discord_event_id: str) -> list[dict]:
    return _q("participantes:listParticipantesByEvento", {
        "discord_event_id": str(discord_event_id),
    }) or []


# ───────────────────────────── assistidos ──

def add_assistido(filme_id: str, user_id: str, username: str | None,
                  display_name: str | None, avatar: str | None,
                  source: str = "manual") -> dict:
    return _m("assistidos:add", _clean({
        "filme_id": filme_id,
        "user_id": str(user_id),
        "username": username,
        "display_name": display_name,
        "avatar": avatar,
        "source": source,
    }))


def exists_assistido(filme_id: str, user_id: str) -> bool:
    return bool(_q("assistidos:existsByFilmeUser", {
        "filme_id": filme_id, "user_id": str(user_id),
    }))


def remove_assistido(filme_id: str, user_id: str) -> int:
    return _m("assistidos:removeByFilmeUser", {
        "filme_id": filme_id, "user_id": str(user_id),
    })


def list_assistidos(filme_id: str) -> list[dict]:
    return _q("assistidos:listByFilme", {"filme_id": filme_id}) or []


def distinct_assistidos_filme_ids() -> set[str]:
    return set(_q("assistidos:distinctFilmeIds", {}) or [])
