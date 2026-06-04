"""Sincroniza participantes de sessões Discord → usuarios_assistidos."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Awaitable, Callable

import convex_db
from evento_service import listar_usuarios_evento_discord

if TYPE_CHECKING:
    import discord


async def coletar_participantes(
    guild: "discord.Guild | None",
    row: dict,
    discord_event_id: str,
    upsert_participante: Callable[..., Awaitable[None]],
    *,
    snapshot_canal: bool = True,
) -> list[dict]:
    """Interessados + voz (snapshot) + inscritos na API do Discord."""
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

    participantes = await asyncio.to_thread(
        convex_db.list_participantes_evento, discord_event_id,
    )
    by_id = {p["user_id"]: p for p in participantes}

    guild_id = str(row.get("guild_id") or (guild.id if guild else ""))
    if guild_id:
        api_users = await asyncio.to_thread(
            listar_usuarios_evento_discord, guild_id, discord_event_id,
        )
        for u in api_users:
            uid = u["user_id"]
            if uid in by_id:
                continue
            by_id[uid] = u
            await upsert_participante(
                discord_event_id, uid, u.get("username", ""), interessado=1,
            )

    return list(by_id.values())


def _perfil_membro(
    guild: "discord.Guild | None", user_id: str, fallback: dict,
) -> tuple[str, str, str | None]:
    username = fallback.get("username") or ""
    display = username
    avatar = None
    if not guild:
        return username, display, avatar
    try:
        member = guild.get_member(int(user_id))
        if member:
            display = member.display_name or member.global_name or member.name
            username = member.name
            if member.avatar:
                avatar = member.avatar.key
    except Exception:
        pass
    return username, display, avatar


async def registrar_assistidos_do_evento(
    guild: "discord.Guild | None",
    row: dict,
    participantes: list[dict],
) -> int:
    """Grava participantes em usuarios_assistidos. Retorna quantos foram inseridos."""
    filme_id, titulo = row["filme_id"], row["titulo"]
    ja = {a["user_id"] for a in await asyncio.to_thread(convex_db.list_assistidos, filme_id)}
    inseridos = 0

    for p in participantes:
        user_id = p["user_id"]
        if user_id in ja:
            continue
        username, display, avatar = _perfil_membro(guild, user_id, p)
        res = await asyncio.to_thread(
            convex_db.add_assistido,
            filme_id, user_id, username, display, avatar, "evento",
        )
        if res.get("inserted"):
            inseridos += 1
            ja.add(user_id)

    if participantes:
        p0 = participantes[0]
        u0, d0, av = _perfil_membro(guild, p0["user_id"], p0)
        await asyncio.to_thread(
            convex_db.marcar_assistido,
            p0["user_id"], filme_id, titulo,
            username=u0,
            display_name=d0,
            avatar=av,
            source="evento",
        )
    elif await asyncio.to_thread(convex_db.get_status_by_filme, filme_id) != "assistido":
        await asyncio.to_thread(convex_db.set_status, filme_id, "assistido")

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
        assistidos = await asyncio.to_thread(convex_db.list_assistidos, filme_id)
        parts_db = await asyncio.to_thread(convex_db.list_participantes_evento, eid)
        ids_reg = {a["user_id"] for a in assistidos}
        falta = [p for p in parts_db if p["user_id"] not in ids_reg]
        tem_fonte_evento = any(a.get("source") == "evento" for a in assistidos)
        if not falta and tem_fonte_evento and len(parts_db) <= len(assistidos):
            continue
        guild_id = str(ev.get("guild_id") or "")
        guild = guild_resolver(guild_id) if guild_id else None
        participantes = await coletar_participantes(
            guild, ev, eid, upsert_participante, snapshot_canal=False,
        )
        if not participantes:
            continue
        n = await registrar_assistidos_do_evento(guild, ev, participantes)
        if n:
            print(f"[Sync evento] {ev.get('titulo')}: +{n} em Assistido Por")
            total += n
    return total


def recuperar_filme_por_id(filme_id: str) -> dict:
    """
    Recupera Assistido Por a partir do último evento encerrado do filme (sem Discord.py).
    Retorna resumo {filme_id, titulo, participantes, inseridos}.
    """
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

    eid = str(ev["discord_event_id"])
    by_id: dict[str, dict] = {}
    for p in convex_db.list_participantes_evento(eid):
        by_id[p["user_id"]] = p

    guild_id = str(ev.get("guild_id") or "")
    if guild_id:
        for u in listar_usuarios_evento_discord(guild_id, eid):
            uid = u["user_id"]
            if uid not in by_id:
                by_id[uid] = u
                convex_db.upsert_participante(
                    eid, uid, u.get("username", ""), interessado=1,
                )

    participantes = list(by_id.values())
    ja = {a["user_id"] for a in convex_db.list_assistidos(filme_id)}
    inseridos = 0
    titulo = ev.get("titulo") or filme_id

    for p in participantes:
        uid = p["user_id"]
        if uid in ja:
            continue
        nome = p.get("username") or ""
        res = convex_db.add_assistido(
            filme_id, uid, nome, nome, None, "evento",
        )
        if res.get("inserted"):
            inseridos += 1
            ja.add(uid)

    if participantes:
        p0 = participantes[0]
        convex_db.marcar_assistido(
            p0["user_id"], filme_id, titulo,
            username=p0.get("username"),
            display_name=p0.get("username"),
            source="evento",
        )
    else:
        convex_db.set_status(filme_id, "assistido")

    return {
        "ok": True,
        "filme_id": filme_id,
        "titulo": titulo,
        "event_id": eid,
        "inseridos": inseridos,
        "participantes": participantes,
    }
