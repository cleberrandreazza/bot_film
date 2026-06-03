"""Criação de eventos agendados no Discord (REST API) — compartilhado com o site."""

import base64
import os
import re
from datetime import datetime, timedelta, timezone

import requests

import convex_db
from event_cover_utils import genero_para_evento, preparar_capa_evento
from synopsis_utils import sinopse_para_filme

BRT = timezone(timedelta(hours=-3))
_DISCORD_API = "https://discord.com/api/v10"
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CineBotecao/1.0)"}

_DIAS_SEMANA_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
_HORAS_EVENTO = (
    "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00",
)
_EVENTO_DURACAO_PADRAO_MIN = 120
_EVENTO_DURACAO_MIN_MIN = 30
_EVENTO_DURACAO_MAX_MIN = 480

OMDB_KEY = os.environ.get("OMDB_API_KEY", "").strip()


def _bot_token() -> str:
    return os.environ.get("DISCORD_TOKEN", "").strip()


def _guild_id() -> str:
    return os.environ.get("DISCORD_GUILD_ID", "").strip()


def _voice_channel_id() -> str:
    return os.environ.get("EVENTO_VOICE_CHANNEL_ID", "").strip()


def _announce_channel_id() -> str:
    return os.environ.get("EVENTO_ANNOUNCE_CHANNEL_ID", "").strip()


def _notify_role_id() -> str:
    return os.environ.get(
        "EVENTO_CINEFILO_ROLE_ID",
        os.environ.get("EVENTO_NOTIFY_ROLE_ID", "1508308918353526814"),
    ).strip()


def opcoes_data() -> list[dict]:
    now = datetime.now(BRT)
    out = []
    for offset in range(90):
        day = now.date() + timedelta(days=offset)
        valor = day.strftime("%d/%m/%Y")
        abrev = day.strftime("%d/%m")
        wd = _DIAS_SEMANA_PT[day.weekday()]
        if offset == 0:
            rotulo = f"Hoje · {abrev} ({wd})"
        elif offset == 1:
            rotulo = f"Amanhã · {abrev} ({wd})"
        else:
            rotulo = f"{wd} · {valor}"
        out.append({"value": valor, "label": rotulo})
    return out


def opcoes_hora() -> list[str]:
    return list(_HORAS_EVENTO)


def limites_picker_evento() -> dict:
    """Metadados do picker do site (mesmo fuso e opções do /evento no Discord)."""
    now = datetime.now(BRT)
    max_day = now.date() + timedelta(days=90)
    return {
        "timezone_label": "Horário de Brasília (BRT)",
        "min_date": now.date().isoformat(),
        "max_date": max_day.isoformat(),
    }


def opcoes_picker_evento() -> dict:
    """Opções de data/hora idênticas aos selects do comando /evento."""
    return {
        **limites_picker_evento(),
        "datas": opcoes_data(),
        "horas": opcoes_hora(),
    }


def _parse_runtime_minutes(runtime: str) -> int | None:
    if not runtime:
        return None
    s = runtime.strip().lower()
    total = 0
    h = re.search(r"(\d+)\s*h", s)
    m = re.search(r"(\d+)\s*min", s)
    if h:
        total += int(h.group(1)) * 60
    if m:
        total += int(m.group(1))
    if total > 0:
        return total
    only_digits = re.fullmatch(r"\d+", s.replace(" ", ""))
    if only_digits:
        return int(only_digits.group(0))
    return None


def _fetch_omdb(imdb_id: str) -> dict | None:
    if not OMDB_KEY or not imdb_id:
        return None
    try:
        r = requests.get(
            "https://www.omdbapi.com/",
            params={"apikey": OMDB_KEY, "i": imdb_id, "plot": "full"},
            headers=_HTTP_HEADERS,
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if data.get("Response") == "True":
                return data
    except Exception as e:
        print(f"[Evento] OMDB: {e}")
    return None


def _omdb_valor(val) -> str:
    if not val or str(val).upper() == "N/A":
        return ""
    return str(val).strip()


def _parse_data_evento(data: str, now: datetime) -> datetime | None:
    data = data.strip()
    alias = data.lower().replace("ã", "a")
    if alias == "hoje":
        return datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    if alias == "amanha":
        d = now.date() + timedelta(days=1)
        return datetime(d.year, d.month, d.day, tzinfo=now.tzinfo)
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d/%m"):
        try:
            dt = datetime.strptime(data, fmt)
            if fmt == "%d/%m":
                dt = dt.replace(year=now.year)
                if dt.date() < now.date():
                    dt = dt.replace(year=now.year + 1)
            return dt.replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
    return None


def parse_data_hora(data: str, hora: str) -> tuple[datetime | None, str | None]:
    data = (data or "").strip()
    hora = (hora or "").strip().replace("h", ":").rstrip(":")
    if ":" not in hora:
        hora = hora + ":00"

    now = datetime.now(BRT)
    dt = _parse_data_evento(data, now)
    if not dt:
        return None, "Data inválida. Use dd/mm/aaaa ou escolha na lista."

    try:
        t = datetime.strptime(hora, "%H:%M").time()
        if t.minute % 15 != 0:
            return None, (
                "O Discord só aceita horários de 15 em 15 minutos "
                "(ex.: 20:00, 20:15, 20:30)."
            )
        dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0, tzinfo=BRT)
    except ValueError:
        return None, "Hora inválida. Use HH:MM (ex: 20:00)."

    if dt < datetime.now(BRT):
        return None, "A data/hora do evento já passou."
    return dt, None


def _duracao_evento(imdb_id: str, omdb_data: dict | None = None) -> timedelta:
    data = omdb_data or _fetch_omdb(imdb_id)
    mins = _parse_runtime_minutes(data.get("Runtime", "")) if data else None
    if mins:
        mins = max(_EVENTO_DURACAO_MIN_MIN, min(mins, _EVENTO_DURACAO_MAX_MIN))
        return timedelta(minutes=mins)
    return timedelta(minutes=_EVENTO_DURACAO_PADRAO_MIN)


def _formatar_duracao(minutos: int) -> str:
    if minutos >= 60:
        h, m = divmod(minutos, 60)
        return f"{h}h {m:02d}min" if m else f"{h}h"
    return f"{minutos} min"


def _descricao_evento(
    canal_nome: str,
    duracao_min: int,
    ano: str,
    genero: str,
    sinopse: str,
) -> str:
    partes = []
    meta = []
    if ano:
        meta.append(f"**Ano:** {ano}")
    if genero:
        meta.append(f"**Gênero:** {genero}")
    if meta:
        partes.append(" · ".join(meta))
    if sinopse:
        texto = sinopse if len(sinopse) <= 600 else sinopse[:597] + "..."
        partes.append(f"\n{texto}")
    partes.append(
        f"\nDuração prevista: **{_formatar_duracao(duracao_min)}**.\n\n"
        f"Marque como **Interessado** e entre no canal **{canal_nome}** "
        f"durante o evento para registrar sua presença."
    )
    return "\n".join(partes)[:1000]


def _discord_headers() -> dict:
    token = _bot_token()
    return {
        **_HTTP_HEADERS,
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }


def _nome_canal_voz() -> tuple[str | None, str | None]:
    """Retorna (channel_id, nome) ou (None, mensagem_erro)."""
    cid = _voice_channel_id()
    if not cid:
        return None, (
            "Canal de voz do evento não configurado "
            "(EVENTO_VOICE_CHANNEL_ID)."
        )
    try:
        r = requests.get(
            f"{_DISCORD_API}/channels/{cid}",
            headers=_discord_headers(),
            timeout=8,
        )
        if r.ok:
            return cid, r.json().get("name") or "voz"
    except Exception as e:
        print(f"[Evento] Canal voz: {e}")
    return cid, "voz"


def _canais_aviso(canal_extra: str | None = None) -> list[str]:
    """Ordem igual ao bot: EVENTO_ANNOUNCE_CHANNEL_ID, depois canal extra (/evento)."""
    ids: list[str] = []
    principal = _announce_channel_id()
    if principal:
        ids.append(principal)
    extra = (canal_extra or "").strip()
    if extra and extra not in ids:
        ids.append(extra)
    return ids


def _publicar_aviso(event_url: str, canal_extra: str | None = None) -> str | None:
    """Retorna aviso se falhou em todos os canais; None se publicou."""
    candidatos = _canais_aviso(canal_extra)
    if not candidatos:
        return "Evento criado, mas o aviso não foi publicado (canal não configurado)."
    role_id = _notify_role_id()
    content = f"Novo evento marcado <@&{role_id}>\n{event_url}" if role_id else (
        f"Novo evento marcado\n{event_url}"
    )
    payload = {
        "content": content,
        "allowed_mentions": {"roles": [role_id]} if role_id else {},
    }
    for canal_id in candidatos:
        try:
            r = requests.post(
                f"{_DISCORD_API}/channels/{canal_id}/messages",
                headers=_discord_headers(),
                json=payload,
                timeout=10,
            )
            if r.ok:
                return None
            print(f"[Evento] Aviso HTTP {r.status_code} em {canal_id}: {r.text[:200]}")
        except Exception as e:
            print(f"[Evento] Aviso em {canal_id}: {e}")
    return "Evento criado, mas o aviso não foi publicado no Discord."


def criar_evento_agendado(
    filme_id: str,
    titulo: str,
    capa_url: str,
    data: str,
    hora: str,
    ano_imdb: str = "",
    *,
    announce_channel_id: str | None = None,
) -> tuple[dict | None, str | None]:
    """
    Cria scheduled event no Discord e registro no Convex.
    Retorna ({"event_id", "event_url", "warning"?}, erro).
    """
    gid = _guild_id()
    if not gid or not _bot_token():
        return None, "Bot Discord não configurado no servidor (DISCORD_TOKEN / DISCORD_GUILD_ID)."

    dt, erro = parse_data_hora(data, hora)
    if erro:
        return None, erro

    channel_id, canal_erro = _nome_canal_voz()
    if not channel_id:
        return None, canal_erro

    omdb_data = _fetch_omdb(filme_id)
    if omdb_data:
        meta = {
            "ano": _omdb_valor(omdb_data.get("Year", ""))[:4],
            "genero": _omdb_valor(omdb_data.get("Genre", "")),
            "sinopse": _omdb_valor(omdb_data.get("Plot", "")),
        }
    else:
        meta = {"ano": "", "genero": "", "sinopse": ""}

    ano_evt = meta["ano"] or (ano_imdb or "")[:4]
    genero_evt = genero_para_evento(filme_id, meta["genero"])
    titulo_omdb = _omdb_valor(omdb_data.get("Title", "")) if omdb_data else ""
    sinopse_evt = sinopse_para_filme(
        titulo, ano_evt, titulo_omdb, meta["sinopse"], filme_id
    )

    duracao = _duracao_evento(filme_id, omdb_data)
    duracao_min = int(duracao.total_seconds() // 60)
    fim = dt + duracao

    _, canal_nome = _nome_canal_voz()
    descricao = _descricao_evento(canal_nome or "voz", duracao_min, ano_evt, genero_evt, sinopse_evt)

    payload = {
        "name": f"🎬 {titulo}",
        "description": descricao,
        "scheduled_start_time": dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scheduled_end_time": fim.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "privacy_level": 2,
        "entity_type": 2,
        "channel_id": int(channel_id),
    }

    capa_bytes = preparar_capa_evento(filme_id, capa_url or "")
    if capa_bytes:
        payload["image"] = base64.b64encode(capa_bytes).decode("ascii")

    try:
        r = requests.post(
            f"{_DISCORD_API}/guilds/{gid}/scheduled-events",
            headers=_discord_headers(),
            json=payload,
            timeout=20,
        )
        if not r.ok and "image" in payload:
            payload.pop("image", None)
            r = requests.post(
                f"{_DISCORD_API}/guilds/{gid}/scheduled-events",
                headers=_discord_headers(),
                json=payload,
                timeout=20,
            )
        if not r.ok:
            msg = "Erro ao criar o evento no Discord."
            try:
                detail = r.json()
                if isinstance(detail, dict) and detail.get("message"):
                    msg = detail["message"]
            except Exception:
                pass
            return None, msg
        ev = r.json()
    except Exception as e:
        return None, f"Erro ao criar o evento: {e}"

    event_id = str(ev.get("id", ""))
    event_url = f"https://discord.com/events/{gid}/{event_id}"

    try:
        convex_db.criar_evento(
            event_id,
            filme_id,
            titulo,
            dt.isoformat(),
            channel_id,
            gid,
        )
    except Exception as e:
        print(f"[Evento] Convex: {e}")

    warning = _publicar_aviso(event_url, announce_channel_id)
    result = {"event_id": event_id, "event_url": event_url}
    if warning:
        result["warning"] = warning
    return result, None
