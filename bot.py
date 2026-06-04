import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import requests
import random
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta

import convex_db
from sorteio_utils import sortear_fila_bot
from synopsis_utils import sinopse_para_filme
from event_cover_utils import preparar_capa_evento, genero_para_evento
from evento_service import criar_evento_agendado, listar_usuarios_evento_discord

# ---- CONFIGURAÇÃO INICIAL DO BOT ----
def _env_to_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


intents = discord.Intents.default()
# Privileged intents are opt-in via env vars to avoid deploy crash
# when they are not enabled in the Discord Developer Portal.
intents.message_content = _env_to_bool("DISCORD_INTENT_MESSAGE_CONTENT", False)
intents.voice_states = True
intents.guild_scheduled_events = True
intents.members = _env_to_bool("DISCORD_INTENT_MEMBERS", False)
bot = commands.Bot(command_prefix="$", intents=intents)
bot.remove_command('help')


def _resolve_web_url() -> str:
    def _normalize_url(value: str) -> str:
        cleaned = value.strip()
        # Aceita valor colado como Markdown: [texto](url)
        if cleaned.startswith("[") and "](" in cleaned and cleaned.endswith(")"):
            try:
                cleaned = cleaned.split("](", 1)[1][:-1].strip()
            except Exception:
                pass
        if cleaned and not cleaned.startswith(("http://", "https://")):
            cleaned = f"https://{cleaned.lstrip('/')}"
        return cleaned

    explicit_url = os.environ.get("WEB_URL")
    if explicit_url:
        return _normalize_url(explicit_url)
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        return _normalize_url(f"https://{railway_domain}")
    port = os.environ.get("PORT", os.environ.get("WEB_PORT", "5000"))
    return _normalize_url(f"http://localhost:{port}")


WEB_URL = _resolve_web_url()
EVENTO_VOICE_CHANNEL_ID = os.environ.get("EVENTO_VOICE_CHANNEL_ID", "").strip()
EVENTO_VOICE_CHANNEL_NAME = os.environ.get("EVENTO_VOICE_CHANNEL_NAME", "").strip()
EVENTO_ANNOUNCE_CHANNEL_ID = os.environ.get("EVENTO_ANNOUNCE_CHANNEL_ID", "").strip()
EVENTO_NOTIFY_ROLE_ID = 1508308918353526814
OMDB_API_KEY = os.environ.get("OMDB_API_KEY", "").strip()
_EVENTO_DURACAO_PADRAO_MIN = 120
_EVENTO_DURACAO_MIN_MIN = 30
_EVENTO_DURACAO_MAX_MIN = 480

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🚀 Bot Coletivo de Filmes Online como {bot.user}")
    print("📦 Banco de dados: Convex (persistente)")
    print(
        "⚙️ Intents: "
        f"message_content={intents.message_content}, "
        f"members={intents.members}, "
        f"voice_states={intents.voice_states}, "
        f"guild_scheduled_events={intents.guild_scheduled_events}"
    )


# ---- FUNÇÃO AUXILIAR: BUSCAR NO IMDB POR NOME ----
def buscar_imdb(nome_filme):
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{requests.utils.quote(nome_filme.lower())}.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resposta = requests.get(url, headers=headers, timeout=5)
        if resposta.status_code == 200:
            dados = resposta.json()
            if 'd' in dados and len(dados['d']) > 0:
                for item in dados['d']:
                    if 'q' in item and item['q'] in ['feature', 'TV series', 'TV movie', 'video']:
                        return {
                            'id': item['id'],
                            'titulo': item['l'],
                            'ano': item.get('y', 'N/A'),
                            'capa': item.get('i', {}).get('imageUrl', ''),
                            'elenco': item.get('s', 'Sem informações de elenco.')
                        }
                primeiro = dados['d'][0]
                return {
                    'id': primeiro['id'],
                    'titulo': primeiro['l'],
                    'ano': primeiro.get('y', 'N/A'),
                    'capa': primeiro.get('i', {}).get('imageUrl', ''),
                    'elenco': primeiro.get('s', 'Sem informações de elenco.')
                }
    except Exception as e:
        print(f"Erro na busca do IMDb: {e}")
    return None


# ---- FUNÇÃO AUXILIAR: BUSCAR NO IMDB POR ID DIRETO ----
def buscar_imdb_por_id(imdb_id):
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{imdb_id}.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        resposta = requests.get(url, headers=headers, timeout=5)
        if resposta.status_code == 200:
            dados = resposta.json()
            if 'd' in dados and len(dados['d']) > 0:
                for item in dados['d']:
                    if item['id'] == imdb_id:
                        return {
                            'id': item['id'],
                            'titulo': item['l'],
                            'ano': item.get('y', 'N/A'),
                            'capa': item.get('i', {}).get('imageUrl', ''),
                            'elenco': item.get('s', 'Sem informações de elenco.')
                        }
    except Exception as e:
        print(f"Erro ao buscar ID do IMDb: {e}")
    return None


def _parse_runtime_minutes(runtime: str) -> int | None:
    if not runtime or runtime.upper() == "N/A":
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
    if not OMDB_API_KEY or not imdb_id:
        return None
    try:
        resp = requests.get(
            "https://www.omdbapi.com/",
            params={"apikey": OMDB_API_KEY, "i": imdb_id, "plot": "full"},
            timeout=8,
        )
        if resp.ok:
            data = resp.json()
            if data.get("Response") == "True":
                return data
    except Exception as e:
        print(f"[Evento] Erro ao buscar OMDB: {e}")
    return None


def buscar_duracao_filme(imdb_id: str) -> int | None:
    """Duração em minutos via OMDB (ex.: '142 min')."""
    data = _fetch_omdb(imdb_id)
    if data:
        return _parse_runtime_minutes(data.get("Runtime", ""))
    return None


def _omdb_valor(val) -> str:
    if not val or str(val).upper() == "N/A":
        return ""
    return str(val).strip()


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


def _ano_filme_imdb(filme_id: str) -> str:
    detalhes = buscar_imdb_por_id(filme_id)
    if not detalhes:
        return ""
    ano = str(detalhes.get("ano") or "")
    return "" if ano == "N/A" else ano


# ================================================================
# LÓGICA DOS COMANDOS (compartilhada entre $ e /)
# ================================================================

def _discord_profile(user) -> dict:
    display = (
        getattr(user, "global_name", None)
        or getattr(user, "display_name", None)
        or user.name
    )
    avatar = user.avatar.key if user.avatar else None
    return {"username": user.name, "display_name": display, "avatar": avatar}


async def _ajuda(send):
    embed = discord.Embed(
        title="🤖 Guia de Comandos — Cinema Coletivo",
        description="Lista de comandos disponíveis via slash (/).",
        color=0x2ecc71
    )
    embed.add_field(
        name="🧩 Comandos Slash `/`",
        value=(
            "`/ajuda` — Mostra este guia.\n"
            "`/biblioteca` — Abre o site do Cine do Botecão.\n"
            "`/adicionar [filme]` — Adiciona um filme à fila.\n"
            "`/visto [filme]` — Marca filme como assistido.\n"
            "`/remover [filme]` — Remove filme da base.\n"
            "`/sorteio` — Sorteia um filme da fila (ignora os em cartaz)."
        ),
        inline=False,
    )
    embed.add_field(
        name="📅 `/evento` — Sessão de cinema",
        value=(
            "Agenda uma sessão coletiva no Discord.\n\n"
            "**Exemplo:**\n"
            "`/evento filme:Inception`\n\n"
            "**Parâmetros:**\n"
            "• **filme** — da fila ou busca no IMDb\n"
            "• Depois, escolha **data** e **hora** nos menus (só você vê)\n\n"
            "A duração do evento segue o filme (OMDB). "
            "Usa sempre a sala de voz configurada no servidor (`EVENTO_VOICE_CHANNEL_ID`). "
            "Quem marcar **Interessado** e entrar na sala é contabilizado. "
            "Ao encerrar, o filme vai para **Já Vistos**."
        ),
        inline=False,
    )
    embed.add_field(
        name="🗑️ `/excluir_evento` — Cancelar sessão",
        value=(
            "**Exemplo:**\n"
            "`/excluir_evento filme:Inception`\n\n"
            "Cancela um evento agendado (autocomplete lista sessões ativas)."
        ),
        inline=False,
    )
    embed.set_footer(text="Use / para todos os comandos")
    await send(embed=embed)


async def _adicionar(send, author, nome_do_filme):
    user_id = str(author.id)
    profile = _discord_profile(author)
    await send(f"🔍 Procurando **{nome_do_filme}** no IMDb...")
    filme = buscar_imdb(nome_do_filme)
    if not filme:
        await send("❌ Filme não encontrado no IMDb. Verifique o nome (nomes em inglês funcionam melhor!).")
        return

    status_existente = await asyncio.to_thread(convex_db.get_status_by_filme, filme['id'])

    if status_existente:
        status_atual = "Fila (Watchlist)" if status_existente == "watchlist" else "Assistidos"
        await send(f"⚠️ **{filme['titulo']}** já está na lista do servidor como *{status_atual}*!")
    else:
        await asyncio.to_thread(
            convex_db.add_filme,
            user_id, filme['id'], filme['titulo'], "watchlist",
            **profile,
        )
        embed = discord.Embed(
            title=f"🍿 {filme['titulo']} ({filme['ano']})",
            description=f"**Estrelando:** {filme['elenco']}\n\nAdicionado à fila do servidor!",
            color=0xF5C518
        )
        embed.add_field(name="🔗 Link IMDb", value=f"https://www.imdb.com/title/{filme['id']}/")
        if filme['capa']:
            embed.set_image(url=filme['capa'])
        await send(embed=embed)


async def _visto(send, author, nome_do_filme):
    user_id = str(author.id)
    profile = _discord_profile(author)
    resultado = await asyncio.to_thread(convex_db.search_watchlist_by_titulo, nome_do_filme)

    if resultado:
        filme_id, titulo = resultado["filme_id"], resultado["titulo"]
        await asyncio.to_thread(
            convex_db.add_assistido,
            filme_id, user_id,
            profile.get("username"), profile.get("display_name"),
            profile.get("avatar"), "discord",
        )
        await asyncio.to_thread(
            convex_db.marcar_assistido,
            user_id, filme_id, titulo, **profile,
        )
        await send(f"✅ **{titulo}** foi movido para os **Assistidos** do grupo!")
    else:
        await send(f"🔍 Não achei **{nome_do_filme}** na fila. Buscando no IMDb para marcar direto...")
        filme = buscar_imdb(nome_do_filme)
        if not filme:
            await send("❌ Filme não encontrado.")
            return

        await asyncio.to_thread(
            convex_db.marcar_assistido,
            user_id, filme['id'], filme['titulo'],
            **profile,
        )
        await send(f"✅ **{filme['titulo']}** adicionado direto nos **Assistidos**!")


async def _remover(send, nome_do_filme):
    resultado = await asyncio.to_thread(convex_db.search_any_by_titulo, nome_do_filme)

    if resultado:
        filme_id, titulo = resultado["filme_id"], resultado["titulo"]
        await asyncio.to_thread(convex_db.remove_by_filme, filme_id)
        await send(f"🗑️ **{titulo}** foi removido da lista global.")
    else:
        await send(f"❌ Não achei nenhum filme com o nome parecido com **{nome_do_filme}**.")


async def _lista(send):
    watchlist = await asyncio.to_thread(convex_db.list_titulos_by_status, "watchlist")
    assistidos = await asyncio.to_thread(convex_db.list_titulos_by_status, "assistido")

    embed = discord.Embed(title="🎬 Catálogo de Cinema do Servidor", color=0x3498db)
    txt_watchlist = "\n".join([f"• {t}" for t in watchlist]) if watchlist else "*Nenhum filme na fila.*"
    txt_assistidos = "\n".join([f"• {t}" for t in assistidos]) if assistidos else "*Nenhum filme assistido ainda.*"
    embed.add_field(name="🍿 Para Assistir (Fila Geral)", value=txt_watchlist, inline=False)
    embed.add_field(name="✅ Já Vistos pela Galera",       value=txt_assistidos, inline=False)
    await send(embed=embed)


async def _sorteio(send):
    watchlist = await asyncio.to_thread(convex_db.list_watchlist_filmes)

    if not watchlist:
        await send("❌ A fila está vazia! Use `$adicionar` ou `/adicionar` para colocar filmes na lista.")
        return

    await send("🎲 Sorteando… (amostra de 10, ignorando cartaz e evento no Discord)")
    bloqueados = await asyncio.to_thread(convex_db.filme_ids_com_evento_ativo)
    try:
        _, (filme_id, titulo) = await asyncio.to_thread(
            sortear_fila_bot,
            watchlist,
            bloqueados,
            get_filme_id=lambda par: par[0],
            get_titulo=lambda par: par[1],
            get_ano=lambda par: _ano_filme_imdb(par[0]),
        )
    except ValueError as e:
        codigo = str(e)
        if codigo == "sem_elegiveis_evento":
            await send(
                "❌ Nenhum filme elegível para sortear (todos com **sessão no Discord**).\n"
                "Cancele ou encerre um evento (`/excluir_evento`) antes de sortear de novo."
            )
            return
        if codigo == "todos_em_cartaz":
            await send(
                "❌ Os candidatos desta rodada estão **em cartaz** ou **ainda não lançados**.\n"
                "Tente de novo ou adicione outros títulos à fila."
            )
            return
        raise
    detalhes = buscar_imdb_por_id(filme_id)

    if detalhes:
        embed = discord.Embed(
            title=f"🎲 Sorteado: {detalhes['titulo']} ({detalhes['ano']})",
            description=f"**Estrelando:** {detalhes['elenco']}\n\nEsse foi o escolhido da fila — hora de assistir!",
            color=0xe67e22
        )
        embed.add_field(name="🔗 Link IMDb", value=f"https://www.imdb.com/title/{detalhes['id']}/")
        if detalhes['capa']:
            embed.set_image(url=detalhes['capa'])
        await send(embed=embed)
    else:
        await send(f"🎲 O sorteado foi: **{titulo}** — hora de assistir!")


# ================================================================
# COMANDOS DE PREFIXO ($)
# ================================================================

@bot.command(name="ajuda", aliases=["help"])
async def cmd_ajuda(ctx):
    await _ajuda(ctx.send)

@bot.command(name="adicionar")
async def cmd_adicionar(ctx, *, nome_do_filme: str):
    await _adicionar(ctx.send, ctx.author, nome_do_filme)

@bot.command(name="visto")
async def cmd_visto(ctx, *, nome_do_filme: str):
    await _visto(ctx.send, ctx.author, nome_do_filme)

@bot.command(name="remover")
async def cmd_remover(ctx, *, nome_do_filme: str):
    await _remover(ctx.send, nome_do_filme)

@bot.command(name="sorteio")
async def cmd_sorteio(ctx):
    await _sorteio(ctx.send)

@bot.command(name="biblioteca")
async def cmd_biblioteca(ctx):
    embed = discord.Embed(
        title="🎬 Cine do Botecão",
        description=f"Acesse a biblioteca completa de filmes do grupo:\n\n<{WEB_URL}>",
        color=0x00e054,
    )
    embed.add_field(name="📋 Na Fila",        value="Filmes aguardando sessão",       inline=True)
    embed.add_field(name="✅ Já Vistos",       value="Histórico do grupo",             inline=True)
    await ctx.send(embed=embed)


# ================================================================
# COMANDOS SLASH (/)
# ================================================================

@bot.tree.command(name="biblioteca", description="🎬 Abre o site do Cine do Botecão")
async def slash_biblioteca(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎬 Cine do Botecão",
        description=f"Acesse a biblioteca completa de filmes do grupo:\n\n<{WEB_URL}>",
        color=0x00e054,
    )
    embed.add_field(name="📋 Na Fila",        value="Filmes aguardando sessão",       inline=True)
    embed.add_field(name="✅ Já Vistos",       value="Histórico do grupo",             inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ajuda", description="Mostra todos os comandos disponíveis")
async def slash_ajuda(interaction: discord.Interaction):
    await interaction.response.defer()
    await _ajuda(interaction.followup.send)

@bot.tree.command(name="adicionar", description="Busca no IMDb e adiciona o filme à fila")
@app_commands.describe(nome_do_filme="Nome do filme para buscar no IMDb")
async def slash_adicionar(interaction: discord.Interaction, nome_do_filme: str):
    await interaction.response.defer()
    await _adicionar(interaction.followup.send, interaction.user, nome_do_filme)

@bot.tree.command(name="visto", description="Move o filme da fila para a lista de Assistidos")
@app_commands.describe(nome_do_filme="Nome do filme para marcar como visto")
async def slash_visto(interaction: discord.Interaction, nome_do_filme: str):
    await interaction.response.defer()
    await _visto(interaction.followup.send, interaction.user, nome_do_filme)

@bot.tree.command(name="remover", description="Remove o filme de todas as listas do servidor")
@app_commands.describe(nome_do_filme="Nome do filme para remover")
async def slash_remover(interaction: discord.Interaction, nome_do_filme: str):
    await interaction.response.defer()
    await _remover(interaction.followup.send, nome_do_filme)

@bot.tree.command(
    name="sorteio",
    description="Sorteia um filme da fila (exclui os que estão em cartaz no cinema)",
)
async def slash_sorteio(interaction: discord.Interaction):
    await interaction.response.defer()
    await _sorteio(interaction.followup.send)


# ================================================================
# COMANDO: EVENTO
# ================================================================

_DIAS_SEMANA_PT = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")
_HORAS_EVENTO_SUGESTAO = (
    "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00",
)


def _parse_data_evento(data: str, now: datetime) -> datetime | None:
    """Interpreta data (dd/mm, aliases ou autocomplete)."""
    data = data.strip()
    alias = data.lower().replace("ã", "a")
    if alias == "hoje":
        return datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
    if alias == "amanha":
        d = now.date() + timedelta(days=1)
        return datetime(d.year, d.month, d.day, tzinfo=now.tzinfo)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d/%m"):
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


def _sugestoes_data_evento(current: str) -> list[app_commands.Choice]:
    """Próximas datas para autocomplete (máx. 25 opções do Discord)."""
    BRT = timezone(timedelta(hours=-3))
    now = datetime.now(BRT)
    needle = (current or "").strip().lower()
    choices: list[app_commands.Choice] = []
    for offset in range(90):
        if len(choices) >= 25:
            break
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
        if needle:
            haystack = f"{rotulo} {valor} {abrev} hoje amanha".lower()
            if needle not in haystack:
                continue
        choices.append(app_commands.Choice(name=rotulo[:100], value=valor[:100]))
    return choices


def _sugestoes_hora_evento(current: str) -> list[app_commands.Choice]:
    needle = (current or "").strip().lower().replace("h", ":")
    choices: list[app_commands.Choice] = []
    for hora in _HORAS_EVENTO_SUGESTAO:
        if needle and needle not in hora:
            continue
        choices.append(app_commands.Choice(name=hora, value=hora))
        if len(choices) >= 25:
            break
    return choices


def _parse_data_hora(data: str, hora: str):
    """Converte strings de data e hora para datetime BRT (UTC-3)."""
    BRT = timezone(timedelta(hours=-3))
    data  = data.strip()
    hora  = hora.strip().replace('h', ':').rstrip(':')
    if ':' not in hora:
        hora = hora + ':00'

    now = datetime.now(BRT)
    dt = _parse_data_evento(data, now)
    if not dt:
        return None, "Data inválida. Use **dd/mm** ou **dd/mm/aaaa** (ou escolha na lista)."

    try:
        t = datetime.strptime(hora, '%H:%M').time()
        dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0, tzinfo=BRT)
    except ValueError:
        return None, "Hora inválida. Use **HH:MM** (ex: 20:00)."

    if dt < datetime.now(BRT):
        return None, "A data/hora do evento já passou."
    return dt, None


async def _get_evento_voice_channel(guild: discord.Guild) -> discord.VoiceChannel | None:
    if EVENTO_VOICE_CHANNEL_ID:
        ch = guild.get_channel(int(EVENTO_VOICE_CHANNEL_ID))
        if isinstance(ch, discord.VoiceChannel):
            return ch
        try:
            ch = await guild.fetch_channel(int(EVENTO_VOICE_CHANNEL_ID))
            if isinstance(ch, discord.VoiceChannel):
                return ch
        except Exception:
            pass
    if EVENTO_VOICE_CHANNEL_NAME:
        for ch in guild.voice_channels:
            if ch.name == EVENTO_VOICE_CHANNEL_NAME:
                return ch
    return None


async def _get_evento_notify_role(guild: discord.Guild) -> discord.Role | None:
    """Role mencionada ao criar evento (ID fixo)."""
    role = guild.get_role(EVENTO_NOTIFY_ROLE_ID)
    if role:
        return role
    try:
        return await guild.fetch_role(EVENTO_NOTIFY_ROLE_ID)
    except (discord.NotFound, discord.HTTPException):
        return None


async def _get_evento_announce_channel(
    guild: discord.Guild,
    interaction: discord.Interaction,
) -> discord.TextChannel | discord.Thread | None:
    """Canal público do aviso: EVENTO_ANNOUNCE_CHANNEL_ID ou canal do /evento."""
    candidatos: list[int] = []
    if EVENTO_ANNOUNCE_CHANNEL_ID:
        try:
            candidatos.append(int(EVENTO_ANNOUNCE_CHANNEL_ID))
        except ValueError:
            print(f"[Evento] EVENTO_ANNOUNCE_CHANNEL_ID inválido: {EVENTO_ANNOUNCE_CHANNEL_ID}")
    if interaction.channel_id and interaction.channel_id not in candidatos:
        candidatos.append(interaction.channel_id)

    for cid in candidatos:
        ch = guild.get_channel(cid)
        if ch is None:
            try:
                ch = await guild.fetch_channel(cid)
            except (discord.NotFound, discord.HTTPException):
                ch = None
        if isinstance(ch, (discord.TextChannel, discord.Thread)):
            return ch
    return None


def _texto_aviso_evento(
    event_url: str,
    role: discord.Role | None,
) -> tuple[str, discord.AllowedMentions]:
    """Mensagem pública com ping na role e link do evento Discord."""
    if role:
        return (
            f"Novo evento marcado {role.mention}\n{event_url}",
            discord.AllowedMentions(roles=[role]),
        )
    return f"Novo evento marcado\n{event_url}", discord.AllowedMentions.none()


async def _enviar_aviso_evento_publico(
    interaction: discord.Interaction,
    event_url: str,
    role: discord.Role | None,
) -> bool:
    """Publica aviso no canal com menção à role e link do evento."""
    canal = await _get_evento_announce_channel(interaction.guild, interaction)
    me = interaction.guild.me
    if not canal:
        print("[Evento] Nenhum canal de texto para aviso público.")
        return False
    if not me:
        print("[Evento] Bot sem membro no servidor.")
        return False

    perms = canal.permissions_for(me)
    if not perms.send_messages:
        print(f"[Evento] Sem permissão de enviar em #{canal.name}.")
        return False
    if role and not perms.mention_everyone:
        print(
            f"[Evento] Bot sem 'Mencionar @everyone/cargos' em #{canal.name} — "
            "ping da role pode falhar."
        )

    texto, mentions = _texto_aviso_evento(event_url, role)
    try:
        if role and not role.mentionable:
            print(
                f"[Evento] Role '{role.name}' não está como mencionável; "
                "usando permissão MENTION_EVERYONE do bot."
            )
        await canal.send(content=texto, allowed_mentions=mentions)
        print(f"[Evento] Aviso publicado em #{canal.name} (id {canal.id}).")
        return True
    except discord.HTTPException as e:
        print(f"[Evento] Erro ao publicar aviso em #{canal.name}: {e}")
        return False


def _descricao_evento(
    canal: discord.VoiceChannel,
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
        f"Marque como **Interessado** e entre no canal **{canal.name}** "
        f"durante o evento para registrar sua presença."
    )
    desc = "\n".join(partes)
    return desc[:1000]


async def _get_evento_ativo_por_titulo(titulo: str):
    return await asyncio.to_thread(convex_db.get_evento_ativo_by_titulo, titulo)


def _opcoes_select_data() -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=c.name, value=c.value)
        for c in _sugestoes_data_evento("")
    ]


def _opcoes_select_hora() -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=h, value=h)
        for h in _HORAS_EVENTO_SUGESTAO
    ]


async def _resolver_filme_evento(filme: str) -> tuple[str, str, str, str] | None:
    """Retorna filme_id, titulo, capa_url, ano_imdb ou None se não achar."""
    row = await asyncio.to_thread(convex_db.search_any_by_titulo, filme)
    capa_url, ano_imdb = "", ""
    if row:
        filme_id, titulo = row["filme_id"], row["titulo"]
        detalhes = buscar_imdb_por_id(filme_id)
        if detalhes:
            capa_url = detalhes.get("capa") or ""
            ano_imdb = str(detalhes.get("ano") or "")
            if ano_imdb == "N/A":
                ano_imdb = ""
        return filme_id, titulo, capa_url, ano_imdb
    found = buscar_imdb(filme)
    if not found:
        return None
    filme_id, titulo = found["id"], found["titulo"]
    capa_url = found.get("capa") or ""
    ano_imdb = str(found.get("ano") or "")
    if ano_imdb == "N/A":
        ano_imdb = ""
    return filme_id, titulo, capa_url, ano_imdb


async def _criar_evento_discord(
    interaction: discord.Interaction,
    filme_id: str,
    titulo: str,
    capa_url: str,
    ano_imdb: str,
    data: str,
    hora: str,
) -> bool:
    """Mesmo fluxo do site: evento_service.criar_evento_agendado + aviso público."""
    canal_extra = str(interaction.channel_id) if interaction.channel_id else None
    resultado, erro = await asyncio.to_thread(
        criar_evento_agendado,
        filme_id,
        titulo,
        capa_url,
        data,
        hora,
        ano_imdb,
        announce_channel_id=canal_extra,
    )
    if erro:
        await interaction.followup.send(f"❌ {erro}", ephemeral=True)
        return False
    aviso = (resultado or {}).get("warning")
    if aviso:
        await interaction.followup.send(f"⚠️ {aviso}", ephemeral=True)
    return True


class EventoAgendarView(discord.ui.View):
    """Menus de data/hora — o Discord não tem datepicker em slash commands."""

    def __init__(
        self,
        author_id: int,
        filme_id: str,
        titulo: str,
        capa_url: str,
        ano_imdb: str,
    ):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.filme_id = filme_id
        self.titulo = titulo
        self.capa_url = capa_url
        self.ano_imdb = ano_imdb
        self.data_val: str | None = None
        self.hora_val: str | None = None
        self.add_item(EventoDataSelect())
        self.add_item(EventoHoraSelect())
        self.add_item(EventoConfirmarButton())

    def _mensagem_status(self) -> str:
        data_txt = f"`{self.data_val}`" if self.data_val else "_não escolhida_"
        hora_txt = f"`{self.hora_val}`" if self.hora_val else "_não escolhida_"
        return (
            f"📅 Agendar sessão: **{self.titulo}**\n\n"
            f"Use os menus abaixo (não é campo de texto):\n"
            f"• **Data:** {data_txt}\n"
            f"• **Hora:** {hora_txt} _(Brasília)_"
        )

    def _atualizar_botao(self):
        for item in self.children:
            if isinstance(item, EventoConfirmarButton):
                item.disabled = not (self.data_val and self.hora_val)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Só quem usou `/evento` pode escolher data e hora.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class EventoDataSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="📅 Escolha a data",
            options=_opcoes_select_data(),
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EventoAgendarView = self.view
        view.data_val = self.values[0]
        view._atualizar_botao()
        await interaction.response.edit_message(
            content=view._mensagem_status(), view=view
        )


class EventoHoraSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="🕐 Escolha o horário",
            options=_opcoes_select_hora(),
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: EventoAgendarView = self.view
        view.hora_val = self.values[0]
        view._atualizar_botao()
        await interaction.response.edit_message(
            content=view._mensagem_status(), view=view
        )


class EventoConfirmarButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Criar sessão",
            style=discord.ButtonStyle.green,
            disabled=True,
            emoji="✅",
        )

    async def callback(self, interaction: discord.Interaction):
        view: EventoAgendarView = self.view
        if not view.data_val or not view.hora_val:
            await interaction.response.send_message(
                "Escolha data e hora nos menus acima.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        ok = await _criar_evento_discord(
            interaction,
            view.filme_id,
            view.titulo,
            view.capa_url,
            view.ano_imdb,
            view.data_val,
            view.hora_val,
        )
        if ok:
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                pass


@bot.tree.command(name="evento", description="📅 Cria uma sessão de cinema no servidor")
@app_commands.describe(filme="Filme da fila (autocomplete) ou busca livre")
async def criar_evento_cmd(interaction: discord.Interaction, filme: str):
    resolved = await _resolver_filme_evento(filme)
    if not resolved:
        await interaction.response.send_message(
            f"❌ Filme **{filme}** não encontrado.", ephemeral=True
        )
        return
    filme_id, titulo, capa_url, ano_imdb = resolved
    view = EventoAgendarView(
        interaction.user.id, filme_id, titulo, capa_url, ano_imdb
    )
    await interaction.response.send_message(
        view._mensagem_status(),
        view=view,
        ephemeral=True,
    )


@bot.tree.command(name="excluir_evento", description="🗑️ Cancela uma sessão de cinema agendada")
@app_commands.describe(filme="Sessão a cancelar (autocomplete)")
async def excluir_evento_cmd(interaction: discord.Interaction, filme: str):
    await interaction.response.defer()

    row = await _get_evento_ativo_por_titulo(filme)
    if not row:
        await interaction.followup.send(
            f"❌ Nenhuma sessão ativa encontrada para **{filme}**."
        )
        return

    discord_event_id, titulo = row["discord_event_id"], row["titulo"]

    try:
        discord_event = await interaction.guild.fetch_scheduled_event(int(discord_event_id))
        await discord_event.delete()
    except discord.NotFound:
        pass
    except Exception as e:
        await interaction.followup.send(f"❌ Erro ao cancelar no Discord: {e}")
        return

    await asyncio.to_thread(convex_db.set_evento_status, discord_event_id, "cancelado")

    await interaction.followup.send(
        f"🗑️ Sessão de **{titulo}** cancelada com sucesso."
    )


@excluir_evento_cmd.autocomplete("filme")
async def excluir_evento_autocomplete(interaction: discord.Interaction, current: str):
    rows = await asyncio.to_thread(
        convex_db.list_eventos_ativos, current or None, 8
    )
    choices = []
    for r in rows:
        titulo = r.get("titulo", "")
        data_evento = r.get("data_evento", "")
        label = titulo[:80]
        if data_evento:
            label = f"{titulo[:60]} ({data_evento[:10]})"[:100]
        choices.append(app_commands.Choice(name=label, value=titulo[:100]))
    return choices


@criar_evento_cmd.autocomplete('filme')
async def evento_filme_autocomplete(interaction: discord.Interaction, current: str):
    if current:
        titulos = await asyncio.to_thread(convex_db.search_titulos, current, 8)
    else:
        titulos = await asyncio.to_thread(convex_db.list_titulos_by_status, "watchlist")
        titulos = titulos[:8]
    return [app_commands.Choice(name=t[:100], value=t[:100]) for t in titulos]


# ================================================================
# RASTREAMENTO DE EVENTOS
# ================================================================

async def _upsert_participante(discord_event_id: str, user_id: str, username: str, **flags):
    await asyncio.to_thread(
        convex_db.upsert_participante, str(discord_event_id), str(user_id), username, **flags
    )


async def _get_evento_by_discord_id(discord_event_id: str):
    return await asyncio.to_thread(convex_db.get_evento_by_discord, str(discord_event_id))


async def _snapshot_canal_evento(guild: discord.Guild, row: dict, discord_event_id: str):
    """Marca quem está no canal de voz do evento (inclui quem já estava lá)."""
    canal_id = row.get("canal_id")
    if not canal_id:
        return
    ch = guild.get_channel(int(canal_id))
    if not isinstance(ch, (discord.VoiceChannel, discord.StageChannel)):
        return
    for member in ch.members:
        if member.bot:
            continue
        nome = member.display_name or member.name
        await _upsert_participante(discord_event_id, str(member.id), nome, entrou_canal=1)


async def _coletar_participantes_evento(
    guild: discord.Guild, row: dict, discord_event_id: str,
) -> list[dict]:
    await _snapshot_canal_evento(guild, row, discord_event_id)

    participantes = await asyncio.to_thread(
        convex_db.list_participantes_evento, discord_event_id,
    )
    by_id = {p["user_id"]: p for p in participantes}

    guild_id = str(row.get("guild_id") or guild.id)
    api_users = await asyncio.to_thread(
        listar_usuarios_evento_discord, guild_id, discord_event_id,
    )
    for u in api_users:
        uid = u["user_id"]
        if uid in by_id:
            continue
        by_id[uid] = u
        await _upsert_participante(
            discord_event_id, uid, u.get("username", ""), interessado=1,
        )

    return list(by_id.values())


@bot.event
async def on_scheduled_event_user_add(event: discord.ScheduledEvent, user: discord.User):
    """Usuário marcou Interessado no evento."""
    row = await _get_evento_by_discord_id(event.id)
    if not row:
        return
    await _upsert_participante(str(event.id), str(user.id), user.name, interessado=1)


@bot.event
async def on_scheduled_event_user_remove(event: discord.ScheduledEvent, user: discord.User):
    """Usuário removeu o Interessado."""
    row = await _get_evento_by_discord_id(event.id)
    if not row:
        return
    await _upsert_participante(str(event.id), str(user.id), user.name, interessado=0)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    """Rastreia entrada em canal de voz durante evento ativo."""
    if not after.channel:
        return
    evento = await asyncio.to_thread(convex_db.get_evento_ativo_by_canal, str(after.channel.id))
    if not evento:
        return
    await _upsert_participante(
        evento["discord_event_id"], str(member.id), member.name, entrou_canal=1
    )


@bot.event
async def on_scheduled_event_update(
    before: discord.ScheduledEvent,
    after: discord.ScheduledEvent,
):
    """Quando o evento inicia ou termina, sincroniza participantes e assistidos."""
    row = await _get_evento_by_discord_id(after.id)
    if not row:
        return

    event_id = str(after.id)

    if (
        after.status == discord.EventStatus.active
        and before.status != discord.EventStatus.active
    ):
        await _snapshot_canal_evento(after.guild, row, event_id)
        await asyncio.to_thread(convex_db.set_evento_status, event_id, "ativo")
        return

    if after.status != discord.EventStatus.completed:
        return

    filme_id, titulo = row["filme_id"], row["titulo"]
    participantes = await _coletar_participantes_evento(after.guild, row, event_id)

    for p in participantes:
        user_id = p["user_id"]
        username = p.get("username") or ""
        display = username
        avatar = None
        try:
            member = after.guild.get_member(int(user_id))
            if member:
                display = member.display_name or member.global_name or member.name
                username = member.name
                if member.avatar:
                    avatar = member.avatar.key
        except Exception:
            pass

        await asyncio.to_thread(
            convex_db.add_assistido,
            filme_id, user_id, username, display, avatar, "evento",
        )

    if participantes:
        p0 = participantes[0]
        await asyncio.to_thread(
            convex_db.marcar_assistido,
            p0["user_id"], filme_id, titulo,
            username=p0.get("username"),
            display_name=p0.get("username"),
            source="evento",
        )
    else:
        await asyncio.to_thread(convex_db.set_status, filme_id, "assistido")

    await asyncio.to_thread(convex_db.set_evento_status, event_id, "encerrado")

    channel = after.guild.system_channel or next(
        (c for c in after.guild.text_channels if c.permissions_for(after.guild.me).send_messages),
        None
    )
    if channel:
        if participantes:
            nomes = ", ".join(f"<@{p['user_id']}>" for p in participantes)
            await channel.send(
                f"✅ Sessão de **{titulo}** encerrada! "
                f"Registrado como assistido para: {nomes}"
            )
        else:
            await channel.send(
                f"✅ Sessão de **{titulo}** encerrada! "
                f"Ninguém foi registrado como participante "
                f"(marque **Interessado** ou entre no canal de voz durante a sessão)."
            )


# ---- EXECUÇÃO DO BOT ----
def _start_web_server():
    from web import app

    port = int(os.environ.get("PORT", os.environ.get("WEB_PORT", "5000")))
    os.environ["WEB_PORT"] = str(port)

    def _run():
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    threading.Thread(target=_run, daemon=True).start()
    print(f"🌐 Biblioteca web ativa em {WEB_URL} (porta {port})")


_start_web_server()
bot.run(os.environ.get('DISCORD_TOKEN'))
