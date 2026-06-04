"""Sincroniza participantes de sessões Discord → usuarios_assistidos."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable

import convex_db
from discord_profiles import buscar_perfil_usuario, enriquecer_perfis
from evento_service import listar_usuarios_evento_discord

if TYPE_CHECKING:
    import discord


def _participantes_todos_eventos_filme(filme_id: str) -> list[dict]:
    """Une participantes de todos os eventos Discord ligados ao filme."""
    by_id: dict[str, dict] = {}
    for ev in convex_db.list_eventos_by_filme(filme_id):
        eid = str(ev.get("discord_event_id", ""))
        if not eid:
            continue
        for p in convex_db.list_participantes_evento(eid):
            uid = p["user_id"]
            if uid not in by_id:
                by_id[uid] = p
    return list(by_id.values())


def _resolver_perfil(
    guild: "discord.Guild | None", user_id: str, fallback: dict,
) -> tuple[str, str, str | None]:
    username = fallback.get("username") or ""
    display = fallback.get("display_name") or username
    avatar = fallback.get("avatar")

    if guild:
        try:
            member = guild.get_member(int(user_id))
            if member:
                display = member.display_name or member.global_name or member.name
                username = member.name
                if member.avatar:
                    avatar = member.avatar.key
                return username, display, avatar
        except Exception:
            pass

    api = buscar_perfil_usuario(user_id)
    if api:
        return (
            api.get("username") or username,
            api.get("display_name") or display,
            api.get("avatar") or avatar,
        )
    return username, display, avatar


async def coletar_participantes(
    guild: "discord.Guild | None",
    row: dict,
    discord_event_id: str,
    upsert_participante: Callable[..., Awaitable[None]],
    *,
    snapshot_canal: bool = True,
    filme_id: str | None = None,
) -> list[dict]:
    """Interessados + voz + inscritos (evento atual e demais do mesmo filme)."""
    if snapshot_canal and guild:
        canal_id = row.get("canal_id")
        if canal_id:
            ch = guild.get_channel(int(canal_id))
            if ch and hasattr(ch, "members"):
                for member in ch.members:
                    if getattr(member, "bot", False):
                        continue
                    nome = getattr(member, "display_name", None) or member.name
                    await upsert_participante(
                        discord_event_id, str(member.id), nome, entrou_canal=1,
                    )

    fid = filme_id or row.get("filme_id")
    by_id: dict[str, dict] = {}
    if fid:
        for p in _participantes_todos_eventos_filme(fid):
            by_id[p["user_id"]] = p

    for p in await asyncio.to_thread(
        convex_db.list_participantes_evento, discord_event_id,
    ):
        by_id[p["user_id"]] = p

    guild_id = str(row.get("guild_id") or (guild.id if guild else ""))
    eventos_api = [discord_event_id]
    if fid:
        eventos_api = list({
            str(e.get("discord_event_id"))
            for e in convex_db.list_eventos_by_filme(fid)
            if e.get("discord_event_id")
        }) or eventos_api

    if guild_id:
        for eid in eventos_api:
            api_users = await asyncio.to_thread(
                listar_usuarios_evento_discord, guild_id, eid,
            )
            for u in api_users:
                uid = u["user_id"]
                by_id[uid] = {**by_id.get(uid, {}), **u}
                await upsert_participante(
                    eid, uid, u.get("username", ""), interessado=1,
                )

    participantes = enriquecer_perfis(list(by_id.values()))
    return participantes


async def registrar_assistidos_do_evento(
    guild: "discord.Guild | None",
    row: dict,
    participantes: list[dict],
) -> int:
    """Grava todos os participantes em usuarios_assistidos com perfil completo."""
    filme_id = row["filme_id"]
    inseridos = 0

    for p in participantes:
        user_id = p["user_id"]
        username, display, avatar = _resolver_perfil(guild, user_id, p)
        res = await asyncio.to_thread(
            convex_db.upsert_assistido,
            filme_id, user_id, username, display, avatar, "evento",
        )
        if res.get("inserted") or res.get("updated"):
            if res.get("inserted"):
                inseridos += 1

    await asyncio.to_thread(convex_db.set_filme_assistido, filme_id)
    return inseridos


async def finalizar_evento(
    guild: "discord.Guild | None",
    row: dict,
    discord_event_id: str,
    upsert_participante: Callable[..., Awaitable[None]],
    *,
    notificar: Callable[[str], Awaitable[None]] | None = None,
) -> list[dict]:
    """Coleta participantes, grava assistidos e encerra o evento no Convex."""
    participantes = await coletar_participantes(
        guild, row, discord_event_id, upsert_participante,
        filme_id=row.get("filme_id"),
    )
    await registrar_assistidos_do_evento(guild, row, participantes)
    await asyncio.to_thread(convex_db.set_evento_status, discord_event_id, "encerrado")

    titulo = row.get("titulo", "Filme")
    if notificar:
        if participantes:
            nomes = ", ".join(f"<@{p['user_id']}>" for p in participantes)
            await notificar(
                f"✅ Sessão de **{titulo}** encerrada! "
                f"Registrado como assistido para: {nomes}"
            )
        else:
            await notificar(
                f"✅ Sessão de **{titulo}** encerrada! "
                f"Ninguém foi registrado como participante "
                f"(marque **Interessado** ou entre no canal de voz durante a sessão)."
            )
    return participantes


async def sincronizar_eventos_encerrados(
    guild_resolver: Callable[[str], "discord.Guild | None"],
    upsert_participante: Callable[..., Awaitable[None]],
) -> int:
    """Repara sessões encerradas sem todos os participantes em Assistido Por."""
    eventos = await asyncio.to_thread(convex_db.list_eventos_by_status, "encerrado")
    total = 0
    for ev in eventos:
        filme_id = ev.get("filme_id")
        eid = str(ev.get("discord_event_id", ""))
        if not filme_id or not eid:
            continue
        guild_id = str(ev.get("guild_id") or "")
        guild = guild_resolver(guild_id) if guild_id else None
        participantes = await coletar_participantes(
            guild, ev, eid, upsert_participante,
            snapshot_canal=False, filme_id=filme_id,
        )
        if not participantes:
            continue
        n = await registrar_assistidos_do_evento(guild, ev, participantes)
        if n:
            print(f"[Sync evento] {ev.get('titulo')}: +{n} em Assistido Por")
            total += n
    return total


def _limpar_lista_anon_polluida(filme_id: str) -> None:
    convex_db.limpar_perfil_anon(filme_id)


def recuperar_filme_por_id(filme_id: str) -> dict:
    """Recupera Assistido Por a partir de eventos do filme (sem Discord.py)."""
    eventos = convex_db.list_eventos_by_filme(filme_id)
    ev = next((e for e in eventos if e.get("status") == "encerrado"), None)
    if not ev:
        ev = next((e for e in eventos), None)
    if not ev:
        lista = convex_db.get_by_filme(filme_id)
        titulo = (lista or {}).get("titulo") or filme_id
        return {
            "ok": False,
            "filme_id": filme_id,
            "titulo": titulo,
            "erro": "Nenhum evento encontrado no Convex para este filme.",
            "inseridos": 0,
            "participantes": [],
        }

    participantes = enriquecer_perfis(_participantes_todos_eventos_filme(filme_id))
    guild_id = str(ev.get("guild_id") or "")
    by_id = {p["user_id"]: p for p in participantes}
    for e in eventos:
        eid = str(e.get("discord_event_id", ""))
        if guild_id and eid:
            for u in listar_usuarios_evento_discord(guild_id, eid):
                by_id[u["user_id"]] = {**by_id.get(u["user_id"], {}), **u}
                convex_db.upsert_participante(
                    eid, u["user_id"], u.get("username", ""), interessado=1,
                )
    participantes = enriquecer_perfis(list(by_id.values()))

    inseridos = 0
    titulo = ev.get("titulo") or filme_id
    for p in participantes:
        uid = p["user_id"]
        api = buscar_perfil_usuario(uid) or p
        res = convex_db.upsert_assistido(
            filme_id, uid,
            api.get("username") or p.get("username"),
            api.get("display_name") or api.get("username") or p.get("username"),
            api.get("avatar"),
            "evento",
        )
        if res.get("inserted"):
            inseridos += 1
        elif res.get("updated"):
            pass

    convex_db.set_filme_assistido(filme_id)
    try:
        _limpar_lista_anon_polluida(filme_id)
    except Exception:
        pass

    return {
        "ok": True,
        "filme_id": filme_id,
        "titulo": titulo,
        "event_id": str(ev.get("discord_event_id")),
        "inseridos": inseridos,
        "participantes": participantes,
    }
