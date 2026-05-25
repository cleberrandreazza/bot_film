import discord
from discord.ext import commands
from imdb import Cinemagoer
import sqlite3
import random
import os

# ---- CONFIGURAÇÃO INICIAL DO BOT ----
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command('help') 

# Inicializa o Cinemagoer injetando cabeçalhos para evitar bloqueios do IMDb
ia = Cinemagoer(headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})

# ---- CONFIGURAÇÃO DO BANCO DE DADOS ----
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


# ---- COMANDO: AJUDA (!help) ----
@bot.command(name="help")
async def ajuda(ctx):
    embed = discord.Embed(
        title="🤖 Guia de Comandos - Gerenciador de Filmes",
        description="Aqui estão todos os comandos para organizar suas sessões de cinema:",
        color=0x2ecc71
    )
    embed.add_field(
        name="🍿 `!adicionar [Nome do Filme]`", 
        value="Busca o filme no IMDb e o adiciona à sua lista de espera (Watchlist).", 
        inline=False
    )
    embed.add_field(
        name="✅ `!visto [Nome do Filme]`", 
        value="Move um filme da lista de espera para 'Assistidos' ou adiciona um filme novo direto como visto.", 
        inline=False
    )
    embed.add_field(
        name="🗑️ `!remover [Nome do Filme]`", 
        value="Deleta permanentemente um filme de qualquer uma das suas listas.", 
        inline=False
    )
    embed.add_field(
        name="🎬 `!minhalista`", 
        value="Mostra o seu catálogo pessoal contendo seus filmes 'Para Assistir' e os 'Já Vistos'.", 
        inline=False
    )
    embed.add_field(
        name="🧠 `!dica`", 
        value="O bot analisa seus gêneros favoritos e recomenda um filme surpresa do IMDb.", 
        inline=False
    )
    embed.set_footer(text="Sempre use o prefixo ! antes de cada comando.")
    await ctx.send(embed=embed)


# ---- COMANDO: ADICIONAR À FILA (WATCHLIST) ----
@bot.command(name="adicionar")
async def adicionar_watchlist(ctx, *, nome_do_filme: str):
    await ctx.send(f"🔍 Procurando '{nome_do_filme}' no IMDb...")
    try:
        resultados = ia.search_movie(nome_do_filme.strip())
        if not resultados:
            await ctx.send("❌ Filme não encontrado no IMDb. Verifique a ortografia ou tente o nome em inglês.")
            return
        
        filme_id = resultados[0].movieID
        titulo = resultados[0]['title']
        user_id = str(ctx.author.id)

        conn = sqlite3.connect('filmes.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT status FROM listas WHERE user_id = ? AND filme_id = ?", (user_id, filme_id))
        existe = cursor.fetchone()
        
        if existe:
            await ctx.send(f"⚠️ **{titulo}** já está na sua lista como *{existe[0]}*!")
        else:
            cursor.execute("INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'watchlist')", (user_id, filme_id, titulo))
            conn.commit()
            await ctx.send(f"🍿 **{titulo}** foi adicionado à sua **Fila (Watchlist)**!")
            
        conn.close()
    except Exception as e:
        print(f"Erro no comando adicionar: {e}")
        await ctx.send("❌ Ocorreu um erro na comunicação com o IMDb. Tente novamente.")


# ---- COMANDO: MARCAR COMO VISTO (ASSISTIDO) ----
@bot.command(name="visto")
async def marcar_assistido(ctx, *, nome_do_filme: str):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    cursor.execute("SELECT filme_id, titulo FROM listas WHERE user_id = ? AND titulo LIKE ? AND status = 'watchlist'", (user_id, f"%{nome_do_filme.strip()}%"))
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo = resultado
        cursor.execute("UPDATE listas SET status = 'assistido' WHERE user_id = ? AND filme_id = ?", (user_id, filme_id))
        conn.commit()
        await ctx.send(f"✅ **{titulo}** movido da fila para a lista de **Assistidos**!")
        conn.close()
    else:
        conn.close()
        await ctx.send(f"🔍 Buscando '{nome_do_filme}' no IMDb para registrar...")
        try:
            resultados = ia.search_movie(nome_do_filme.strip())
            if not resultados:
                await ctx.send("❌ Filme não encontrado no IMDb.")
                return
            filme_id = resultados[0].movieID
            titulo = resultados[0]['title']
            
            conn = sqlite3.connect('filmes.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO listas (user_id, filme_id, titulo, status) VALUES (?, ?, ?, 'assistido')", (user_id, filme_id, titulo))
            conn.commit()
            await ctx.send(f"✅ **{titulo}** adicionado direto na sua lista de **Assistidos**!")
            conn.close()
        except Exception:
            await ctx.send("❌ Erro ao conectar ao IMDb.")


# ---- COMANDO: REMOVER FILME ----
@bot.command(name="remover")
async def remover_filme(ctx, *, nome_do_filme: str):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    cursor.execute("SELECT filme_id, titulo, status FROM listas WHERE user_id = ? AND titulo LIKE ?", (user_id, f"%{nome_do_filme.strip()}%"))
    resultado = cursor.fetchone()

    if resultado:
        filme_id, titulo, status = resultado
        cursor.execute("DELETE FROM listas WHERE user_id = ? AND filme_id = ?", (user_id, filme_id))
        conn.commit()
        
        categoria = "Fila (Watchlist)" if status == "watchlist" else "Assistidos"
        await ctx.send(f"🗑️ **{titulo}** foi removido com sucesso da sua lista de *{categoria}*!")
    else:
        await ctx.send(f"❌ Não encontrei nenhum filme com o nome parecido com '{nome_do_filme}' na sua lista.")
        
    conn.close()


# ---- COMANDO: VISUALIZAR AS LISTAS ----
@bot.command(name="minhalista")
async def mostrar_lista(ctx):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()

    cursor.execute("SELECT titulo FROM listas WHERE user_id = ? AND status = 'watchlist'", (user_id,))
    watchlist = cursor.fetchall()

    cursor.execute("SELECT titulo FROM listas WHERE user_id = ? AND status = 'assistido'", (user_id,))
    assistidos = cursor.fetchall()
    conn.close()

    embed = discord.Embed(title=f"🎬 Catálogo de Cinema - {ctx.author.name}", color=0x3498db)
    
    txt_watchlist = "\n".join([f"• {f[0]}" for f in watchlist]) if watchlist else "*Nenhum filme na fila.*"
    txt_assistidos = "\n".join([f"• {f[0]}" for f in assistidos]) if assistidos else "*Nenhum filme assistido ainda.*"

    embed.add_field(name="🍿 Para Assistir (Watchlist)", value=txt_watchlist, inline=False)
    embed.add_field(name="✅ Já Vistos", value=txt_assistidos, inline=False)

    await ctx.send(embed=embed)


# ---- COMANDO: SISTEMA DE DICAS COM PLANO DE CONTINGÊNCIA ----
@bot.command(name="dica")
async def dar_dica(ctx):
    user_id = str(ctx.author.id)
    conn = sqlite3.connect('filmes.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT filme_id FROM listas 
        WHERE user_id = ? AND status = 'assistido' 
        ORDER BY id DESC LIMIT 5
    """, (user_id,))
    ultimos_assistidos = cursor.fetchall()
    conn.close()

    await ctx.send("🧠 Analisando suas preferências recentes e consultando o IMDb...")

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
                    f"🔥 **Em Alta + O seu Estilo:** Notei que você curte *{genero_favorito_do_momento}*. Que tal esse título que está bombando?"
                )
                return

        top_trends = filmes_em_alta[:10]
        filme_top_trend = random.choice(top_trends)
        filme_detalhes = ia.get_movie(filme_top_trend.movieID)
        
        await enviar_embed_filme(
            ctx, 
            filme_detalhes, 
            "🌍 **Bombando no Mundo:** Aqui está um dos filmes mais quentes do IMDb esta semana!"
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
                "🏛️ **Clássico Recomendado:** Os servidores do IMDb estão instáveis agora, mas aqui está uma recomendação imperdível e aclamada pelo público!"
            )
        except Exception:
            await ctx.send("❌ O sistema do IMDb está fora do ar no momento. Tente novamente em instantes!")

# ---- EXECUÇÃO DO BOT ----
bot.run(os.environ.get('DISCORD_TOKEN'))