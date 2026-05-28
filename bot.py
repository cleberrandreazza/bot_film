import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import requests
import random
import os
from datetime import datetime, timezone, timedelta

# ---- CONFIGURAÇÃO INICIAL DO BOT ----
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guild_scheduled_events = True
intents.members = True
bot = commands.Bot(command_prefix="$", intents=intents)
bot.remove_command('help')

# 💾 BLINDAGEM DO BANCO DE DADOS (PERSISTÊNCIA ABSOLUTA)
if os.path.exists('/data') or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH'):
    DB_PATH = '/data/filmes.db'
else:
    DB_PATH = 'filmes.db'

dirname = os.path.dirname(DB_PATH)
if dirname and not os.path.exists(dirname):
    try:
        os.makedirs(dirname, exist_ok=True)
        print(f"📁 Pasta de volume {dirname} criada com sucesso para persistência.")
    except Exception as e:
        print(f"⚠️ Erro ao criar diretório do volume: {e}")

def iniciar_banco():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS listas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            filme_id TEXT,
            titulo TEXT,
            status TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_event_id TEXT UNIQUE,
            filme_id TEXT NOT NULL,
            titulo TEXT NOT NULL,
            data_evento TEXT NOT NULL,
            canal_id TEXT,
            guild_id TEXT,
            status TEXT DEFAULT 'agendado'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evento_participantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            interessado INTEGER DEFAULT 0,
            entrou_canal INTEGER DEFAULT 0,
            UNIQUE(evento_id, user_id),
            FOREIGN KEY (evento_id) REFERENCES eventos(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios_assistidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filme_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            display_name TEXT,
            avatar TEXT,
            source TEXT DEFAULT 'manual',
            data_assistido TEXT DEFAULT (datetime("now")),
            UNIQUE(filme_id, user_id)
        )
    ''')
    conn.commit()
    conn.close()

iniciar_banco()

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🚀 Bot Coletivo de Filmes Online como {bot.user}")
    print(f"📦 Caminho ativo e seguro do Banco de Dados: {os.path.abspath(DB_PATH)}")


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


# ================================================================
# LÓGICA DOS COMANDOS (compartilhada entre $ e /)
# ================================================================

async def _ajuda(send):
    embed = discord.Embed(
        title="🤖 Guia de Comandos — Cinema Coletivo",
        description="Todos os comandos funcionam com `$` (prefixo) ou `/` (slash).",
        color=0x2ecc71
    )
    embed.add_field(name="🍿 `adicionar [filme]`", value="Busca no IMDb e adiciona o filme à fila do servidor.", inline=False)
    embed.add_field(name="✅ `visto [filme]`",     value="Move o filme da fila para a lista de Assistidos.",    inline=False)
    embed.add_field(name="🗑️ `remover [filme]`",  value="Remove o filme de todas as listas do servidor.",      inline=False)
    embed.add_field(name="🎬 `lista`",             value="Exibe a fila e os filmes já assistidos.",             inline=False)
    embed.add_field(name="🎲 `sorteio`",           value="Sorteia um filme da fila para assistir hoje.",        inline=False)
    embed.add_field(name="🧠 `dica`",              value="Sorteia uma recomendação de filme aclamado.",         inline=False)
    embed.set_footer(text="Use $ ou / como prefixo | Lista 100% Compartilhada")
    await send(embed=embed)


async def _adicionar(send, user_id, nome_do_filme):
    await send(f"🔍 Procurando **{nome_do_filme}** no IMDb...")
    filme = buscar_imdb(nome_do_filme)
    if not filme:
        await send("❌ Filme não encontrado no IMDb. Verifique o nome (nomes em inglês funcionam melhor!).")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM listas WHERE filme_id = ?", (filme['id'],))
    existe = cursor.fetchone()

    if existe:
        status_atual = "Fila (Watchlist)" if existe[0] == "watchlist" else "Assistidos"
        await send(f"⚠️ **{filme['titulo']}** já está na lista do servidor como *{status_atual}*!")
    else:
        cursor.execute(
            "INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'watchlist')",
            (user_id, filme['id'], filme['titulo'])
        )
        conn.commit()
        embed = discord.Embed(
            title=f"🍿 {filme['titulo']} ({filme['ano']})",
            description=f"**Estrelando:** {filme['elenco']}\n\nAdicionado à fila do servidor!",
            color=0xF5C518
        )
        embed.add_field(name="🔗 Link IMDb", value=f"https://www.imdb.com/title/{filme['id']}/")
        if filme['capa']:
            embed.set_image(url=filme['capa'])
        await send(embed=embed)

    conn.close()


async def _visto(send, user_id, nome_do_filme):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT filme_id, titulo FROM listas WHERE titulo LIKE ? AND status = 'watchlist'",
        (f"%{nome_do_filme.strip()}%",)
    )
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo = resultado
        cursor.execute("UPDATE listas SET status = 'assistido' WHERE filme_id = ?", (filme_id,))
        conn.commit()
        conn.close()
        await send(f"✅ **{titulo}** foi movido para os **Assistidos** do grupo!")
    else:
        conn.close()
        await send(f"🔍 Não achei **{nome_do_filme}** na fila. Buscando no IMDb para marcar direto...")
        filme = buscar_imdb(nome_do_filme)
        if not filme:
            await send("❌ Filme não encontrado.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM listas WHERE filme_id = ?", (filme['id'],))
        ja_existe = cursor.fetchone()
        if ja_existe:
            cursor.execute("UPDATE listas SET status = 'assistido' WHERE filme_id = ?", (filme['id'],))
        else:
            cursor.execute(
                "INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'assistido')",
                (user_id, filme['id'], filme['titulo'])
            )
        conn.commit()
        conn.close()
        await send(f"✅ **{filme['titulo']}** adicionado direto nos **Assistidos**!")


async def _remover(send, nome_do_filme):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT filme_id, titulo FROM listas WHERE titulo LIKE ?",
        (f"%{nome_do_filme.strip()}%",)
    )
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo = resultado
        cursor.execute("DELETE FROM listas WHERE filme_id = ?", (filme_id,))
        conn.commit()
        await send(f"🗑️ **{titulo}** foi removido da lista global.")
    else:
        await send(f"❌ Não achei nenhum filme com o nome parecido com **{nome_do_filme}**.")

    conn.close()


async def _lista(send):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT titulo FROM listas WHERE status = 'watchlist'")
    watchlist = cursor.fetchall()
    cursor.execute("SELECT titulo FROM listas WHERE status = 'assistido'")
    assistidos = cursor.fetchall()
    conn.close()

    embed = discord.Embed(title="🎬 Catálogo de Cinema do Servidor", color=0x3498db)
    txt_watchlist = "\n".join([f"• {f[0]}" for f in watchlist]) if watchlist else "*Nenhum filme na fila.*"
    txt_assistidos = "\n".join([f"• {f[0]}" for f in assistidos]) if assistidos else "*Nenhum filme assistido ainda.*"
    embed.add_field(name="🍿 Para Assistir (Fila Geral)", value=txt_watchlist, inline=False)
    embed.add_field(name="✅ Já Vistos pela Galera",       value=txt_assistidos, inline=False)
    await send(embed=embed)


async def _sorteio(send):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT filme_id, titulo FROM listas WHERE status = 'watchlist'")
    watchlist = cursor.fetchall()
    conn.close()

    if not watchlist:
        await send("❌ A fila está vazia! Use `$adicionar` ou `/adicionar` para colocar filmes na lista.")
        return

    filme_id, titulo = random.choice(watchlist)
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


async def _dica(send):
    await send("🧠 Sorteando uma recomendação de peso no acervo do IMDb...")
    filmes_pool = [
        'tt0111161', 'tt0468569', 'tt1375666', 'tt0137523', 'tt0110912',
        'tt0816692', 'tt0109830', 'tt0068646', 'tt6751668', 'tt0499549',
        'tt1160419', 'tt2382320', 'tt0848228', 'tt7286456', 'tt1877830',
        'tt0087332', 'tt0361748', 'tt0993846', 'tt15314262', 'tt11358390',
        'tt2119532', 'tt9362722', 'tt3501632', 'tt12555530', 'tt1630029',
        'tt1517268', 'tt10872600', 'tt1345836', 'tt2049555', 'tt10655866'
    ]
    id_sorteado = random.choice(filmes_pool)
    filme = buscar_imdb_por_id(id_sorteado)

    if filme:
        embed = discord.Embed(
            title=f"🎬 Sugestão: {filme['titulo']} ({filme['ano']})",
            description=f"**Estrelando:** {filme['elenco']}\n\nQue tal reunir a galera do servidor para assistir esse título hoje?",
            color=0x9b59b6
        )
        embed.add_field(name="🔗 Link IMDb", value=f"https://www.imdb.com/title/{filme['id']}/")
        if filme['capa']:
            embed.set_image(url=filme['capa'])
        await send(embed=embed)
    else:
        await send("❌ Tive um problema ao sortear a dica. Tente novamente!")


# ================================================================
# COMANDOS DE PREFIXO ($)
# ================================================================

@bot.command(name="help")
async def cmd_help(ctx):
    await _ajuda(ctx.send)

@bot.command(name="adicionar")
async def cmd_adicionar(ctx, *, nome_do_filme: str):
    await _adicionar(ctx.send, str(ctx.author.id), nome_do_filme)

@bot.command(name="visto")
async def cmd_visto(ctx, *, nome_do_filme: str):
    await _visto(ctx.send, str(ctx.author.id), nome_do_filme)

@bot.command(name="remover")
async def cmd_remover(ctx, *, nome_do_filme: str):
    await _remover(ctx.send, nome_do_filme)

@bot.command(name="lista")
async def cmd_lista(ctx):
    await _lista(ctx.send)

@bot.command(name="sorteio")
async def cmd_sorteio(ctx):
    await _sorteio(ctx.send)

@bot.command(name="dica")
async def cmd_dica(ctx):
    await _dica(ctx.send)


# ================================================================
# COMANDOS SLASH (/)
# ================================================================

@bot.tree.command(name="ajuda", description="Mostra todos os comandos disponíveis")
async def slash_ajuda(interaction: discord.Interaction):
    await interaction.response.defer()
    await _ajuda(interaction.followup.send)

@bot.tree.command(name="adicionar", description="Busca no IMDb e adiciona o filme à fila")
@app_commands.describe(nome_do_filme="Nome do filme para buscar no IMDb")
async def slash_adicionar(interaction: discord.Interaction, nome_do_filme: str):
    await interaction.response.defer()
    await _adicionar(interaction.followup.send, str(interaction.user.id), nome_do_filme)

@bot.tree.command(name="visto", description="Move o filme da fila para a lista de Assistidos")
@app_commands.describe(nome_do_filme="Nome do filme para marcar como visto")
async def slash_visto(interaction: discord.Interaction, nome_do_filme: str):
    await interaction.response.defer()
    await _visto(interaction.followup.send, str(interaction.user.id), nome_do_filme)

@bot.tree.command(name="remover", description="Remove o filme de todas as listas do servidor")
@app_commands.describe(nome_do_filme="Nome do filme para remover")
async def slash_remover(interaction: discord.Interaction, nome_do_filme: str):
    await interaction.response.defer()
    await _remover(interaction.followup.send, nome_do_filme)

@bot.tree.command(name="lista", description="Exibe a fila e os filmes já assistidos")
async def slash_lista(interaction: discord.Interaction):
    await interaction.response.defer()
    await _lista(interaction.followup.send)

@bot.tree.command(name="sorteio", description="Sorteia um filme da fila para assistir hoje")
async def slash_sorteio(interaction: discord.Interaction):
    await interaction.response.defer()
    await _sorteio(interaction.followup.send)

@bot.tree.command(name="dica", description="Sorteia uma recomendação de filme aclamado")
async def slash_dica(interaction: discord.Interaction):
    await interaction.response.defer()
    await _dica(interaction.followup.send)


# ================================================================
# COMANDO: EVENTO
# ================================================================

def _parse_data_hora(data: str, hora: str):
    """Converte strings de data e hora para datetime BRT (UTC-3)."""
    BRT = timezone(timedelta(hours=-3))
    data  = data.strip()
    hora  = hora.strip().replace('h', ':').rstrip(':')
    if ':' not in hora:
        hora = hora + ':00'

    now = datetime.now(BRT)
    dt  = None
    for fmt in ('%d/%m/%Y', '%d/%m/%y', '%d/%m'):
        try:
            dt = datetime.strptime(data, fmt)
            if fmt == '%d/%m':
                dt = dt.replace(year=now.year)
                if dt.date() < now.date():
                    dt = dt.replace(year=now.year + 1)
            break
        except ValueError:
            continue
    if not dt:
        return None, "Data inválida. Use **dd/mm** ou **dd/mm/aaaa**."

    try:
        t = datetime.strptime(hora, '%H:%M').time()
        dt = dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0, tzinfo=BRT)
    except ValueError:
        return None, "Hora inválida. Use **HH:MM** (ex: 20:00)."

    if dt < datetime.now(BRT):
        return None, "A data/hora do evento já passou."
    return dt, None


@bot.tree.command(name="evento", description="📅 Cria uma sessão de cinema no servidor")
@app_commands.describe(
    filme="Filme da fila (autocomplete) ou busca livre",
    data="Data do evento — ex: 25/06",
    hora="Hora do evento — ex: 20:00",
    canal="Canal de voz (opcional)",
)
async def criar_evento_cmd(
    interaction: discord.Interaction,
    filme: str,
    data: str,
    hora: str,
    canal: discord.VoiceChannel = None,
):
    await interaction.response.defer()

    dt, erro = _parse_data_hora(data, hora)
    if erro:
        await interaction.followup.send(f"❌ {erro}")
        return

    # Busca o filme no DB ou no IMDb
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT filme_id, titulo FROM listas WHERE titulo LIKE ? LIMIT 1",
        (f'%{filme.strip()}%',)
    )
    row = cursor.fetchone()
    if row:
        filme_id, titulo = row
    else:
        found = buscar_imdb(filme)
        if not found:
            conn.close()
            await interaction.followup.send(f"❌ Filme **{filme}** não encontrado.")
            return
        filme_id, titulo = found['id'], found['titulo']

    # Acha canal de voz
    if not canal:
        canal = next(
            (c for c in interaction.guild.channels
             if isinstance(c, discord.VoiceChannel)), None
        )
    if not canal:
        conn.close()
        await interaction.followup.send("❌ Nenhum canal de voz encontrado no servidor.")
        return

    # Cria o evento Discord
    try:
        discord_event = await interaction.guild.create_scheduled_event(
            name=f"🎬 {titulo}",
            description=(
                f"Sessão coletiva de cinema!\n\n"
                f"Marque como **Interessado** e entre no canal **{canal.name}** "
                f"durante o evento para registrar sua presença."
            ),
            start_time=dt,
            end_time=dt + timedelta(hours=3),
            channel=canal,
            entity_type=discord.EntityType.voice,
            privacy_level=discord.PrivacyLevel.guild_only,
        )
    except Exception as e:
        conn.close()
        await interaction.followup.send(f"❌ Erro ao criar o evento: {e}")
        return

    cursor.execute(
        "INSERT OR IGNORE INTO eventos "
        "(discord_event_id, filme_id, titulo, data_evento, canal_id, guild_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(discord_event.id), filme_id, titulo,
         dt.isoformat(), str(canal.id), str(interaction.guild.id)),
    )
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="📅 Sessão de Cinema Criada!",
        color=0x00e054,
    )
    embed.add_field(name="🎬 Filme",   value=titulo,                          inline=False)
    embed.add_field(name="📅 Data",    value=dt.strftime('%d/%m/%Y às %H:%M'), inline=True)
    embed.add_field(name="🎙️ Canal",  value=canal.name,                       inline=True)
    embed.set_footer(text="Marque como Interessado no evento e entre no canal para ser contabilizado!")
    await interaction.followup.send(embed=embed)


@criar_evento_cmd.autocomplete('filme')
async def evento_filme_autocomplete(interaction: discord.Interaction, current: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if current:
        cursor.execute(
            "SELECT titulo FROM listas WHERE titulo LIKE ? ORDER BY id DESC LIMIT 8",
            (f'%{current}%',)
        )
    else:
        cursor.execute(
            "SELECT titulo FROM listas WHERE status='watchlist' ORDER BY id DESC LIMIT 8"
        )
    rows = cursor.fetchall()
    conn.close()
    return [app_commands.Choice(name=r[0][:100], value=r[0][:100]) for r in rows]


# ================================================================
# RASTREAMENTO DE EVENTOS
# ================================================================

def _upsert_participante(evento_id: int, user_id: str, username: str, **flags):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    sets   = ', '.join(f"{k}={v}" for k, v in flags.items())
    cursor.execute(
        f"INSERT INTO evento_participantes (evento_id, user_id, username, {', '.join(flags)}) "
        f"VALUES (?, ?, ?, {', '.join('?' for _ in flags)}) "
        f"ON CONFLICT(evento_id, user_id) DO UPDATE SET {sets}",
        (evento_id, user_id, username, *flags.values()),
    )
    conn.commit()
    conn.close()


def _get_evento_by_discord_id(discord_event_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, filme_id, titulo, canal_id FROM eventos WHERE discord_event_id=?",
        (str(discord_event_id),)
    )
    row = cursor.fetchone()
    conn.close()
    return row


@bot.event
async def on_scheduled_event_user_add(event: discord.ScheduledEvent, user: discord.User):
    """Usuário marcou Interessado no evento."""
    row = _get_evento_by_discord_id(event.id)
    if not row:
        return
    evento_id = row[0]
    _upsert_participante(evento_id, str(user.id), user.name, interessado=1)


@bot.event
async def on_scheduled_event_user_remove(event: discord.ScheduledEvent, user: discord.User):
    """Usuário removeu o Interessado."""
    row = _get_evento_by_discord_id(event.id)
    if not row:
        return
    evento_id = row[0]
    _upsert_participante(evento_id, str(user.id), user.name, interessado=0)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
):
    """Rastreia entrada em canal de voz durante evento ativo."""
    if not after.channel:
        return
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM eventos WHERE canal_id=? AND status IN ('agendado','ativo')",
        (str(after.channel.id),)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return
    _upsert_participante(row[0], str(member.id), member.name, entrou_canal=1)


@bot.event
async def on_scheduled_event_update(
    before: discord.ScheduledEvent,
    after: discord.ScheduledEvent,
):
    """Quando o evento termina, registra quem assistiu."""
    if after.status != discord.EventStatus.completed:
        return
    row = _get_evento_by_discord_id(after.id)
    if not row:
        return
    evento_id, filme_id, titulo, _ = row

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Quem marcou interessado E entrou no canal
    cursor.execute(
        "SELECT user_id, username FROM evento_participantes "
        "WHERE evento_id=? AND interessado=1 AND entrou_canal=1",
        (evento_id,)
    )
    participantes = cursor.fetchall()

    for user_id, username in participantes:
        # Tenta buscar avatar via guild member
        avatar = None
        try:
            member = after.guild.get_member(int(user_id))
            if member and member.avatar:
                avatar = member.avatar.key
        except Exception:
            pass

        cursor.execute(
            "INSERT OR IGNORE INTO usuarios_assistidos "
            "(filme_id, user_id, username, display_name, avatar, source) "
            "VALUES (?, ?, ?, ?, ?, 'evento')",
            (filme_id, user_id, username, username, avatar),
        )

    cursor.execute(
        "UPDATE eventos SET status='encerrado' WHERE id=?", (evento_id,)
    )
    conn.commit()
    conn.close()

    # Notifica no canal de texto padrão
    channel = after.guild.system_channel or next(
        (c for c in after.guild.text_channels if c.permissions_for(after.guild.me).send_messages),
        None
    )
    if channel and participantes:
        nomes = ', '.join(f'<@{uid}>' for uid, _ in participantes)
        await channel.send(
            f"✅ Sessão de **{titulo}** encerrada! "
            f"Registrado como assistido para: {nomes}"
        )


# ---- EXECUÇÃO DO BOT ----
bot.run(os.environ.get('DISCORD_TOKEN'))
