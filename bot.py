import discord
from discord.ext import commands
from imdb import Cinemagoer
import sqlite3
import random
import os

# ---- CONFIGURAÇÃO INICIAL DO BOT ----
intents = discord.Intents.default()
intents.message_content = True

# 🌟 TROCA DE PREFIXO: Alterado de '!' para '$' para evitar conflito com outros bots
bot = commands.Bot(command_prefix="$", intents=intents)
bot.remove_command('help') 

# Inicializa o Cinemagoer injetando cabeçalhos para evitar bloqueios do IMDb
ia = Cinemagoer(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})

# ---- CONFIGURAÇÃO DO BANCO DE DADOS (GLOBAL) ----
def iniciar_banco():
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()
    # Mantemos a estrutura, mas o bot não vai mais filtrar por user_id para que a lista seja global
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
    print(f"🚀 Bot de Filmes Online como {bot.user}")

# ---- FUNÇÃO AUXILIAR: FORMATAR E ENVIAR EMBED DO FILME ----
async def enviar_embed_filme(ctx, filme, texto_extra=""):
    titulo = filme.get('title', 'Sem título')
    ano = filme.get('year', 'N/A')
    nota = filme.get('rating', 'Sem nota')
    sinopse = filme.get('plot outline', filme.get('plot', ['Sem sinopse'])[0])
    capa_url = filme.get('full-size cover url', filme.get('cover url', ''))

    if isinstance(sinopse, list): 
        sinopse = sinopse[0]
    sinopse = (sinopse[:250] + '...') if len(sinopse) > 250 else sinopse

    embed = discord.Embed(
        title=f"{titulo} ({ano})", 
        description=sinopse, 
        color=0xF5C518
    )
    embed.add_field(name="⭐ Nota IMDb", value=f"{nota}/10", inline=True)
    embed.add_field(name="🔗 Link", value=f"https://www.imdb.com/title/tt{filme.movieID}/", inline=True)
    
    if capa_url: 
        embed.set_image(url=capa_url)

    await ctx.send(content=texto_extra, embed=embed)


# ---- COMANDO: AJUDA ($help) ----
@bot.command(name="help")
async def ajuda(ctx):
    embed = discord.Embed(
        title="🤖 Guia de Comandos - Gerenciador de Filmes (LISTA GLOBAL)",
        description="Aqui estão todos os comandos compartilhados para organizar o cinema do servidor:",
        color=0x2ecc71
    )
    embed.add_field(
        name="🍿 `$adicionar [Nome do Filme]`", 
        value="Busca no IMDb e adiciona à lista de espera coletiva do servidor.", 
        inline=False
    )
    embed.add_field(
        name="✅ `$visto [Nome do Filme]`", 
        value="Move um filme da fila global para 'Assistidos' ou adiciona um novo direto lá.", 
        inline=False
    )
    embed.add_field(
        name="🗑️ `$remover [Nome do Filme]`", 
        value="Deleta permanentemente um filme da lista global do servidor.", 
        inline=False
    )
    embed.add_field(
        name="🎬 `$minhalista`", 
        value="Mostra o catálogo global completo (Watchlist e Já Vistos) do servidor.", 
        inline=False
    )
    embed.add_field(
        name="🧠 `$dica`", 
        value="Recomenda um filme com base no histórico global ou nos sucessos do IMDb.", 
        inline=False
    )
    embed.set_footer(text="Atenção: O prefixo agora é $")
    await ctx.send(embed=embed)


# ---- COMANDO: ADICIONAR À FILA GLOBAL ----
@bot.command(name="adicionar")
async def adicionar_watchlist(ctx, *, nome_do_filme: str):
    # Força uma busca limpa removendo espaços extras nas pontas e aspas soltas
    busca = nome_do_filme.strip().replace('"', '').replace("'", "")
    await ctx.send(f"🔍 Procurando '{busca}' no IMDb...")
    try:
        resultados = ia.search_movie(busca)
        if not resultados:
            await ctx.send("❌ Filme não encontrado no IMDb. Dica: Tente pesquisar pelo nome original em inglês.")
            return
        
        filme_id = resultados[0].movieID
        titulo = resultados[0]['title']
        user_id = str(ctx.author.id)

        conn = sqlite3.connect('filmes.db')
        cursor = conn.cursor()
        
        # 🌍 BUSCA GLOBAL: Não filtra por user_id
        cursor.execute("SELECT status FROM listas WHERE filme_id = ?", (filme_id,))
        existe = cursor.fetchone()
        
        if existe:
            await ctx.send(f"⚠️ **{titulo}** já está na lista global do servidor como *{existe[0]}*!")
        else:
            cursor.execute("INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'watchlist')", (user_id, filme_id, titulo))
            conn.commit()
            await ctx.send(f"🍿 **{titulo}** foi adicionado à **Fila Global** do servidor!")
            
        conn.close()
    except Exception as e:
        print(f"Erro no comando adicionar: {e}")
        await ctx.send("❌ Ocorreu um erro na comunicação com o IMDb. Tente novamente.")


# ---- COMANDO: MARCAR COMO VISTO NA LISTA GLOBAL ----
@bot.command(name="visto")
async def marcar_assistido(ctx, *, nome_do_filme: str):
    busca = nome_do_filme.strip().replace('"', '').replace("'", "")
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    # 🌍 BUSCA GLOBAL: Procura o filme na watchlist geral
    cursor.execute("SELECT filme_id, titulo FROM listas WHERE titulo LIKE ? AND status = 'watchlist'", (f"%{busca}%",))
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo = resultado
        cursor.execute("UPDATE listas SET status = 'assistido' WHERE filme_id = ?", (filme_id,))
        conn.commit()
        await ctx.send(f"✅ **{titulo}** movido para a lista global de **Assistidos**!")
        conn.close()
    else:
        conn.close()
        await ctx.send(f"🔍 Não achei '{busca}' na fila. Buscando no IMDb para registrar direto como assistido...")
        try:
            resultados = ia.search_movie(busca)
            if not resultados:
                await ctx.send("❌ Filme não encontrado no IMDb.")
                return
            filme_id = resultados[0].movieID
            titulo = resultados[0]['title']
            user_id = str(ctx.author.id)
            
            conn = sqlite3.connect('filmes.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'assistido')", (user_id, filme_id, titulo))
            conn.commit()
            await ctx.send(f"✅ **{titulo}** adicionado direto nos **Assistidos** do servidor!")
            conn.close()
        except Exception:
            await ctx.send("❌ Erro ao conectar ao IMDb.")


# ---- COMANDO: REMOVER DA LISTA GLOBAL ----
@bot.command(name="remover")
async def remover_filme(ctx, *, nome_do_filme: str):
    busca = nome_do_filme.strip().replace('"', '').replace("'", "")
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    # 🌍 REMOÇÃO GLOBAL: Qualquer um pode remover qualquer filme pelo nome aproximado
    cursor.execute("SELECT filme_id, titulo, status FROM listas WHERE titulo LIKE ?", (f"%{busca}%",))
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo, status = resultado
        cursor.execute("DELETE FROM listas WHERE filme_id = ?", (filme_id,))
        conn.commit()
        
        categoria = "Fila (Watchlist)" if status == "watchlist" else "Assistidos"
        await ctx.send(f"🗑️ **{titulo}** foi removido por {ctx.author.name} da lista global de *{categoria}*!")
    else:
        await ctx.send(f"❌ Não encontrei nenhum filme com o nome parecido com '{busca}' na lista do servidor.")
        
    conn.close()


# ---- COMANDO: VISUALIZAR A LISTA GLOBAL ----
@bot.command(name="minhalista")
async def mostrar_lista(ctx):
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    # 🌍 VISUALIZAÇÃO GLOBAL: Traz tudo sem filtrar por usuário
    cursor.execute("SELECT titulo FROM listas WHERE status = 'watchlist'")
    watchlist = cursor.fetchall()

    cursor.execute("SELECT titulo FROM listas WHERE status = 'assistido'")
    assistidos = cursor.fetchall()
    conn.close()

    embed = discord.Embed(title="🎬 Catálogo de Cinema Coletivo do Servidor", color=0x3498db)
    
    txt_watchlist = "\n".join([f"• {f[0]}" for f in watchlist]) if watchlist else "*Nenhum filme na fila.*"
    txt_assistidos = "\n".join([f"• {f[0]}" for f in assistidos]) if assistidos else "*Nenhum filme assistido ainda.*"

    embed.add_field(name="🍿 Para Assistir (Fila Global)", value=txt_watchlist, inline=False)
    embed.add_field(name="✅ Já Vistos pelo Grupo", value=txt_assistidos, inline=False)

    await ctx.send(embed=embed)


# ---- COMANDO: SISTEMA DE DICAS COM PLANO DE CONTINGÊNCIA ----
@bot.command(name="dica")
async def dar_dica(ctx):
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()
    
    # Baseia-se nos últimos filmes assistidos globalmente pelo grupo
    cursor.execute("SELECT filme_id FROM listas WHERE status = 'assistido' ORDER BY id DESC LIMIT 5")
    ultimos_assistidos = cursor.fetchall()
    conn.close()

    await ctx.send("🧠 Analisando os gostos do servidor e consultando o IMDb...")

    contagem_generos = {}
    if ultimos_assistidos:
        for item in ultimos_assistidos:
            f_id = item[0]
            try:
                info_filme = ia.get_movie(f_id)
                for genero in info_filme.get('genres', []):
                    contagem_generos[genero] = contagem_generos.get(genero, 0) + 1
            except Exception:
                continue

    try:
        filmes_em_alta = ia.get_popular100_movies()
        
        if contagem_generos and len(contagem_generos) > 0:
            genero_favorito_do_momento = max(contagem_generos, key=contagem_generos.get)
            amostra_trends = random.sample(filmes_em_alta, min(20, len(filmes_em_alta)))
            filmes_compativeis = []
            
            for f in amostra_trends:
                detalhes = ia.get_movie(f.movieID)
                if genero_favorito_do_momento in detalhes.get('genres', []):
                    filmes_compativeis.append(detalhes)
            
            if filmes_compativeis:
                filme_escolhido = random.choice(filmes_compativeis)
                await enviar_embed_filme(
                    ctx, 
                    filme_escolhido, 
                    f"🔥 **Em Alta + O Estilo do Servidor:** Notei que a galera curte *{genero_favorito_do_momento}*. Que tal esse aqui?"
                )
                return

        top_trends = filmes_em_alta[:10]
        filme_top_trend = random.choice(top_trends)
        filme_detalhes = ia.get_movie(filme_top_trend.movieID)
        
        await enviar_embed_filme(
            ctx, 
            filme_detalhes, 
            "🌍 **Bombando no Mundo:** Aqui está um dos filmes mais quentes do IMDb esta semana para assistirem juntos!"
        )

    except Exception as e:
        print(f"Erro de conexão com a API do IMDb, usando plano de contingência: {e}")
        ids_classicos = ['0111161', '0068646', '0468569', '0137523', '0109830', '0133093', '0110912', '0050813', '0816692', '0167260']
        id_escolhido = random.choice(ids_classicos)
        try:
            filme_detalhes = ia.get_movie(id_escolhido)
            await enviar_embed_filme(
                ctx, 
                filme_detalhes, 
                "🏛️ **Clássico Recomendado:** O IMDb recusou a conexão temporariamente, mas aqui está uma recomendação imperdível para o grupo!"
            )
        except Exception:
            await ctx.send("❌ O sistema do IMDb está fora do ar no momento. Tente novamente em instantes!")

# ---- EXECUÇÃO DO BOT ----
bot.run(os.environ.get('DISCORD_TOKEN'))