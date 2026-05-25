import discord
from discord.ext import commands
import sqlite3
import requests
import random
import os

# ---- CONFIGURAÇÃO INICIAL DO BOT ----
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="$", intents=intents)
bot.remove_command('help') 

# ---- CONFIGURAÇÃO DO BANCO DE DADOS (GLOBAL) ----
def iniciar_banco():
    conn = sqlite3.connect('filmes.db')
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
    conn.commit()
    conn.close()

iniciar_banco()

@bot.event
async def on_ready():
    print(f"🚀 Bot Coletivo de Filmes Online como {bot.user}")

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

# ---- FUNÇÃO AUXILIAR: BUSCAR NO IMDB POR ID DIRECTO (Para o comando !dica) ----
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


# ---- COMANDO: AJUDA ($help) ----
@bot.command(name="help")
async def ajuda(ctx):
    embed = discord.Embed(
        title="🤖 Guia de Comandos - Cinema Coletivo",
        description="Gerencie a lista de filmes do servidor usando os comandos abaixo:",
        color=0x2ecc71
    )
    embed.add_field(name="🍿 `$adicionar [Nome do Filme]`", value="Busca no IMDb e joga na Fila Geral do servidor.", inline=False)
    embed.add_field(name="✅ `$visto [Nome do Filme]`", value="Passa o filme para a lista de 'Assistidos' do grupo.", inline=False)
    embed.add_field(name="🗑️ `$remover [Nome do Filme]`", value="Apaga o filme das listas do grupo.", inline=False)
    embed.add_field(name="🎬 `$minhalista`", value="Exibe a Watchlist e os Já Vistos de todo mundo.", inline=False)
    embed.add_field(name="🧠 `$dica`", value="Sorteia uma recomendação de filme aclamado para o grupo assistir.", inline=False)
    embed.set_footer(text="Prefixo atual: $ | Lista 100% Compartilhada")
    await ctx.send(embed=embed)


# ---- COMANDO: ADICIONAR À FILA ----
@bot.command(name="adicionar")
async def adicionar_watchlist(ctx, *, nome_do_filme: str):
    await ctx.send(f"🔍 Procurando '{nome_do_filme}' diretamente no IMDb...")
    
    filme = buscar_imdb(nome_do_filme)
    if not filme:
        await ctx.send("❌ Filme não encontrado no IMDb. Verifique o nome (nomes em inglês funcionam melhor!).")
        return

    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT status FROM listas WHERE filme_id = ?", (filme['id'],))
    existe = cursor.fetchone()
    
    if existe:
        status_atual = "Fila (Watchlist)" if existe[0] == "watchlist" else "Assistidos"
        await ctx.send(f"⚠️ **{filme['titulo']}** já está na lista do servidor como *{status_atual}*!")
    else:
        cursor.execute("INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'watchlist')", (str(ctx.author.id), filme['id'], filme['titulo']))
        conn.commit()
        
        embed = discord.Embed(title=f"🍿 {filme['titulo']} ({filme['ano']})", description=f"**Estrelando:** {filme['elenco']}\n\nAdicionado à fila do servidor!", color=0xF5C518)
        embed.add_field(name="🔗 Link IMDb", value=f"https://www.imdb.com/title/{filme['id']}/")
        if filme['capa']:
            embed.set_image(url=filme['capa'])
            
        await ctx.send(embed=embed)
        
    conn.close()


# ---- COMANDO: MARCAR COMO VISTO ----
@bot.command(name="visto")
async def marcar_assistido(ctx, *, nome_do_filme: str):
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    cursor.execute("SELECT filme_id, titulo FROM listas WHERE titulo LIKE ? AND status = 'watchlist'", (f"%{nome_do_filme.strip()}%",))
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo = resultado
        cursor.execute("UPDATE listas SET status = 'assistido' WHERE filme_id = ?", (filme_id,))
        conn.commit()
        await ctx.send(f"✅ **{titulo}** foi movido para os **Assistidos** do grupo!")
        conn.close()
    else:
        conn.close()
        await ctx.send(f"🔍 Não achei '{nome_do_filme}' na fila. Buscando no IMDb para marcar direto...")
        filme = buscar_imdb(nome_do_filme)
        if not filme:
            await ctx.send("❌ Filme não encontrado.")
            return
        
        conn = sqlite3.connect('filmes.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'assistido')", (str(ctx.author.id), filme['id'], filme['titulo']))
        conn.commit()
        await ctx.send(f"✅ **{filme['titulo']}** adicionado direto nos **Assistidos**!")
        conn.close()


# ---- COMANDO: REMOVER ----
@bot.command(name="remover")
async def remover_filme(ctx, *, nome_do_filme: str):
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    cursor.execute("SELECT filme_id, titulo FROM listas WHERE titulo LIKE ?", (f"%{nome_do_filme.strip()}%",))
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo = resultado
        cursor.execute("DELETE FROM listas WHERE filme_id = ?", (filme_id,))
        conn.commit()
        await ctx.send(f"🗑️ **{titulo}** foi removido da lista global.")
    else:
        await ctx.send(f"❌ Não achei nenhum filme com o nome parecido com '{nome_do_filme}'.")
        
    conn.close()


# ---- COMANDO: VER LISTA GLOBAL ----
@bot.command(name="minhalista")
async def mostrar_lista(ctx):
    conn = sqlite3.connect('filmes.db')
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
    embed.add_field(name="✅ Já Vistos pela Galera", value=txt_assistidos, inline=False)

    await ctx.send(embed=embed)


# ---- COMANDO: DICA COLETIVA REFORMULADA ----
@bot.command(name="dica")
async def dar_dica(ctx):
    await ctx.send("🧠 Sorteando uma recomendação de peso no acervo do IMDb...")
    
    # Pool variado com ótimos filmes de diversos estilos (Sci-Fi, Ação, Suspense, Drama, Terror)
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
            
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Tive um problema ao sortear a dica. Tente novamente!")

# ---- EXECUÇÃO DO BOT ----
bot.run(os.environ.get('DISCORD_TOKEN'))