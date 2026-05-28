from flask import Flask, render_template, jsonify, abort, request, session, redirect, url_for
import sqlite3
import requests
import re
import os
import time
import random
import urllib.parse

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)

OMDB_KEY             = os.environ.get('OMDB_API_KEY', '')
DISCORD_CLIENT_ID    = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET= os.environ.get('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/callback')
DB_PATH  = '/data/filmes.db' if os.path.exists('/data') else 'filmes.db'

_cache: dict = {}
_TTL = 3600  # 1 hour


def _init_web_tables():
    """Cria todas as tabelas necessárias caso ainda não existam."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS listas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, filme_id TEXT, titulo TEXT, status TEXT
        );
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_event_id TEXT UNIQUE,
            filme_id TEXT NOT NULL, titulo TEXT NOT NULL,
            data_evento TEXT NOT NULL, canal_id TEXT, guild_id TEXT,
            status TEXT DEFAULT "agendado"
        );
        CREATE TABLE IF NOT EXISTS evento_participantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id INTEGER NOT NULL, user_id TEXT NOT NULL,
            username TEXT, interessado INTEGER DEFAULT 0, entrou_canal INTEGER DEFAULT 0,
            UNIQUE(evento_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS usuarios_assistidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filme_id TEXT NOT NULL, user_id TEXT NOT NULL,
            username TEXT, display_name TEXT, avatar TEXT,
            source TEXT DEFAULT "manual",
            data_assistido TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(filme_id, user_id)
        );
    ''')
    conn.commit()
    conn.close()

_init_web_tables()


@app.context_processor
def inject_user():
    u = None
    if 'user_id' in session:
        u = {
            'user_id':      session['user_id'],
            'username':     session.get('username', ''),
            'display_name': session.get('display_name', session.get('username', '')),
            'avatar':       session.get('avatar'),
        }
    return {'current_user': u}

# Pool de filmes para a seção Destaques (mesmo do $dica do bot)
FILMES_POOL = [
    'tt0111161', 'tt0468569', 'tt1375666', 'tt0137523', 'tt0110912',
    'tt0816692', 'tt0109830', 'tt0068646', 'tt6751668', 'tt0499549',
    'tt1160419', 'tt2382320', 'tt0848228', 'tt7286456', 'tt1877830',
    'tt0087332', 'tt0361748', 'tt0993846', 'tt15314262', 'tt11358390',
    'tt2119532', 'tt9362722', 'tt3501632', 'tt12555530', 'tt1630029',
    'tt1517268', 'tt10872600', 'tt1345836', 'tt2049555', 'tt10655866',
]


JW_GRAPHQL = 'https://apis.justwatch.com/graphql'
JW_QUERY = (
    '{ popularTitles(country: BR, first: 3,'
    ' filter: {searchQuery: "%s", objectTypes: [MOVIE]}) {'
    ' edges { node { __typename ... on Movie {'
    ' content(country: BR, language: "pt") { title fullPath }'
    ' offers(country: BR, platform: WEB) {'
    ' monetizationType package { clearName icon } deeplinkURL(platform: WEB)'
    ' } } } } } }'
)


def get_streaming(title: str, year: str) -> list:
    """Busca serviços de streaming no Brasil via JustWatch GraphQL."""
    key = f'jw:{title}:{year}'
    now = time.time()
    if key in _cache and now - _cache[key][1] < _TTL:
        return _cache[key][0]
    try:
        safe_title = title.replace('"', '\\"')
        r = requests.post(
            JW_GRAPHQL,
            json={'query': JW_QUERY % safe_title},
            headers={'User-Agent': 'JustWatch/4.0 (Android)', 'Content-Type': 'application/json'},
            timeout=8,
        )
        if not r.ok:
            return []
        edges = (r.json().get('data') or {}).get('popularTitles', {}).get('edges', [])
        for edge in edges:
            node = edge.get('node', {})
            if node.get('__typename') != 'Movie':
                continue
            content = node.get('content', {})
            seen, result = set(), []
            for o in (node.get('offers') or []):
                if o.get('monetizationType') != 'FLATRATE':
                    continue
                pkg  = o.get('package', {})
                name = pkg.get('clearName', '')
                if name in seen:
                    continue
                seen.add(name)
                icon = pkg.get('icon', '')
                logo = ('https://images.justwatch.com' +
                        icon.replace('{profile}', 's100').replace('{format}', 'webp'))
                result.append({
                    'nome': name,
                    'logo': logo,
                    'url':  o.get('deeplinkURL', ''),
                })
            if result:
                _cache[key] = (result, now)
                return result
    except Exception as e:
        print(f'JustWatch error: {e}')
    empty: list = []
    _cache[key] = (empty, now)
    return empty


def get_pt_synopsis(title: str, year: str) -> str | None:
    """Busca sinopse em português no Wikipedia PT."""
    key = f'wiki:{title}:{year}'
    now = time.time()
    if key in _cache and now - _cache[key][1] < _TTL * 24:
        return _cache[key][0]
    try:
        r = requests.get('https://pt.wikipedia.org/w/api.php', params={
            'action': 'query', 'list': 'search',
            'srsearch': f'{title} {year} filme', 'format': 'json',
            'srlimit': 3, 'utf8': 1,
        }, headers={'User-Agent': 'CinemaColetivo/1.0'}, timeout=5)
        results = (r.json().get('query') or {}).get('search', [])
        if not results:
            return None
        r2 = requests.get('https://pt.wikipedia.org/w/api.php', params={
            'action': 'query', 'prop': 'extracts', 'exintro': 1,
            'explaintext': 1, 'titles': results[0]['title'],
            'format': 'json', 'utf8': 1,
        }, headers={'User-Agent': 'CinemaColetivo/1.0'}, timeout=5)
        pages = (r2.json().get('query') or {}).get('pages', {})
        for page in pages.values():
            extract = (page.get('extract') or '').strip()
            if len(extract) > 80:
                sentences = [s.strip() for s in extract.split('.') if s.strip()]
                synopsis = '. '.join(sentences[:4]) + '.'
                if len(synopsis) > 600:
                    synopsis = synopsis[:600].rsplit(' ', 1)[0] + '…'
                _cache[key] = (synopsis, now)
                return synopsis
    except Exception as e:
        print(f'Wikipedia error: {e}')
    _cache[key] = (None, now)
    return None


_GENERIC_GENRES = {'action', 'comedy', 'animation', 'family', 'drama', 'adventure'}

def get_similar_movies(genres: list, exclude_imdb: str) -> list:
    """Busca 6 filmes similares via JustWatch usando os gêneros do filme."""
    key = f'similar:{exclude_imdb}'
    now = time.time()
    if key in _cache and now - _cache[key][1] < _TTL * 6:
        return _cache[key][0]
    if not genres:
        return []
    # Prefere gêneros específicos; cai no primeiro se todos forem genéricos
    specific = [g for g in genres if g.lower() not in _GENERIC_GENRES]
    chosen   = specific[:2] if specific else genres[:2]
    safe     = ' '.join(chosen).lower().replace('"', '')
    query = (
        '{ popularTitles(country: BR, first: 18,'
        f' filter: {{searchQuery: "{safe}", objectTypes: [MOVIE]}}) {{'
        ' edges { node { __typename ... on Movie {'
        ' content(country: BR, language: "pt") {'
        ' title fullPath'
        ' posterUrl(profile: S718, format: WEBP)'
        ' externalIds { imdbId }'
        ' } } } } } }'
    )
    try:
        r = requests.post(JW_GRAPHQL, json={'query': query},
            headers={'User-Agent': 'JustWatch/4.0 (Android)'}, timeout=8)
        if not r.ok:
            return []
        edges = (r.json().get('data') or {}).get('popularTitles', {}).get('edges', [])
        result, seen = [], set()
        for edge in edges:
            node = edge.get('node', {})
            if node.get('__typename') != 'Movie':
                continue
            c = node.get('content', {})
            imdb_id = (c.get('externalIds') or {}).get('imdbId', '')
            if not imdb_id or imdb_id == exclude_imdb or imdb_id in seen:
                continue
            seen.add(imdb_id)
            poster_path = c.get('posterUrl', '')
            result.append({
                'imdb_id': imdb_id,
                'titulo':  c.get('title', ''),
                'poster':  f'https://images.justwatch.com{poster_path}' if poster_path else '',
            })
            if len(result) >= 6:
                break
        _cache[key] = (result, now)
        return result
    except Exception as e:
        print(f'Similar movies error: {e}')
    return []


def get_trailer_id(title: str, year: str) -> str | None:
    """Obtém o ID do trailer no YouTube via scraping da página de busca."""
    key = f'yt:{title}:{year}'
    now = time.time()
    if key in _cache and now - _cache[key][1] < _TTL * 24:
        return _cache[key][0]
    try:
        q   = f'{title} {year} trailer legendado português'
        url = f'https://www.youtube.com/results?search_query={requests.utils.quote(q)}'
        r   = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'pt-BR,pt;q=0.9',
        }, timeout=8)
        ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', r.text)))
        if ids:
            _cache[key] = (ids[0], now)
            return ids[0]
    except Exception as e:
        print(f'YouTube trailer error: {e}')
    _cache[key] = (None, now)
    return None


def omdb_fetch(imdb_id: str):
    """Busca detalhes no OMDB com cache em memória."""
    if not OMDB_KEY:
        return None
    key = f"omdb:{imdb_id}"
    now = time.time()
    if key in _cache and now - _cache[key][1] < _TTL:
        return _cache[key][0]
    try:
        r = requests.get(
            'https://www.omdbapi.com/',
            params={'apikey': OMDB_KEY, 'i': imdb_id, 'plot': 'full'},
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if data.get('Response') == 'True':
                _cache[key] = (data, now)
                return data
    except Exception:
        pass
    return None


def _parse_movie(imdb_id: str, data: dict) -> dict:
    """Converte resposta do OMDB para dicionário padronizado."""
    def clean(val):
        return val if val and val != 'N/A' else ''

    # Poster — aumenta resolução substituindo o sufixo
    poster = clean(data.get('Poster', ''))
    if poster:
        for old in ('_SX300', '_SX150', '_SX200'):
            poster = poster.replace(f'{old}.jpg', '_SX500.jpg')

    # Runtime numérico
    try:
        duracao = int(data.get('Runtime', '0 min').replace(' min', ''))
    except ValueError:
        duracao = 0

    # Nota numérica
    try:
        nota = round(float(data.get('imdbRating', '0')), 1)
    except ValueError:
        nota = 0.0

    # Votos numérico
    try:
        votos = int(data.get('imdbVotes', '0').replace(',', ''))
    except ValueError:
        votos = 0

    # Listas a partir de strings separadas por vírgula
    genres  = [g.strip() for g in clean(data.get('Genre',  '')).split(',') if g.strip()]
    actors  = [a.strip() for a in clean(data.get('Actors', '')).split(',') if a.strip()]
    diretor = clean(data.get('Director', ''))

    # Ratings extras (RT, Metacritic)
    ratings = {
        r['Source']: r['Value']
        for r in data.get('Ratings', [])
    }

    return {
        'imdb_id':  imdb_id,
        'titulo':   clean(data.get('Title', '')),
        'sinopse':  clean(data.get('Plot',  '')) or 'Sem sinopse disponível.',
        'poster':   poster,
        'ano':      clean(data.get('Year', ''))[:4],
        'nota':     nota,
        'votos':    votos,
        'duracao':  duracao,
        'generos':  genres,
        'diretor':  diretor,
        'elenco':   [{'nome': a, 'personagem': '', 'foto': ''} for a in actors],
        'ratings':  ratings,
        'rated':    clean(data.get('Rated', '')),
        'pais':     clean(data.get('Country', '')),
    }


def get_movie(imdb_id: str):
    data = omdb_fetch(imdb_id)
    if not data:
        return None
    movie = _parse_movie(imdb_id, data)
    if movie:
        movie['streaming']  = get_streaming(movie['titulo'], movie['ano'])
        pt_synopsis         = get_pt_synopsis(movie['titulo'], movie['ano'])
        if pt_synopsis:
            movie['sinopse'] = pt_synopsis
        movie['trailer_id'] = get_trailer_id(movie['titulo'], movie['ano'])
        movie['similares']  = get_similar_movies(movie['generos'], imdb_id)
    return movie


PER_PAGE = 12


def _get_db_rows():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        watchlist  = conn.execute("SELECT * FROM listas WHERE status='watchlist'  ORDER BY id DESC").fetchall()
        assistidos = conn.execute("SELECT * FROM listas WHERE status='assistido'  ORDER BY id DESC").fetchall()
        conn.close()
        return list(watchlist), list(assistidos)
    except Exception:
        return [], []


def _get_db_page(status: str, page: int):
    """Retorna (rows, total) paginado para uma seção do DB."""
    offset = (page - 1) * PER_PAGE
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM listas WHERE status=?", (status,)).fetchone()[0]
        rows  = conn.execute(
            "SELECT * FROM listas WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status, PER_PAGE, offset)
        ).fetchall()
        conn.close()
        return list(rows), total
    except Exception:
        return [], 0


def _omdb_basic(iid: str) -> dict | None:
    data = omdb_fetch(iid)
    if not data:
        return None
    poster = data.get('Poster', '')
    if poster and poster != 'N/A':
        poster = poster.replace('_SX300.jpg', '_SX500.jpg')
    else:
        poster = ''
    return {'imdb_id': iid, 'titulo': data.get('Title', ''),
            'poster': poster, 'ano': (data.get('Year') or '')[:4],
            'nota': data.get('imdbRating', '')}


def _pool_destaques(n=6):
    """Retorna N filmes aleatórios do pool (para a home)."""
    ids    = random.sample(FILMES_POOL, min(n, len(FILMES_POOL)))
    result = [r for iid in ids if (r := _omdb_basic(iid))]
    return result


def _pool_page(page: int):
    """Retorna (filmes, total) do pool paginado (para /filmes/destaques)."""
    start = (page - 1) * PER_PAGE
    ids   = FILMES_POOL[start:start + PER_PAGE]
    result = [r for iid in ids if (r := _omdb_basic(iid))]
    return result, len(FILMES_POOL)


# ─────────────────────────────── helpers ──

def _avatar_url(user_id: str, avatar: str | None) -> str:
    if avatar:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=64"
    idx = (int(user_id) >> 22) % 6
    return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"


def _get_assistidos(imdb_id: str) -> list:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT user_id, username, display_name, avatar, source, data_assistido "
            "FROM usuarios_assistidos WHERE filme_id=? ORDER BY data_assistido ASC",
            (imdb_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ─────────────────────────────── OAuth2 routes ──

@app.route('/auth/login')
def auth_login():
    if not DISCORD_CLIENT_ID:
        return "Discord OAuth2 não configurado.", 503
    next_url = request.args.get('next', '/')
    params = urllib.parse.urlencode({
        'client_id':    DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type':'code',
        'scope':        'identify',
        'state':        next_url,
    })
    return redirect(f'https://discord.com/oauth2/authorize?{params}')


@app.route('/auth/callback')
def auth_callback():
    code     = request.args.get('code')
    next_url = request.args.get('state', '/')
    if not code:
        return redirect('/')
    r = requests.post('https://discord.com/api/oauth2/token', data={
        'client_id':     DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type':    'authorization_code',
        'code':          code,
        'redirect_uri':  DISCORD_REDIRECT_URI,
    }, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=8)
    if not r.ok:
        return redirect('/')
    token = r.json().get('access_token')
    r2 = requests.get('https://discord.com/api/users/@me',
                      headers={'Authorization': f'Bearer {token}'}, timeout=8)
    if not r2.ok:
        return redirect('/')
    u = r2.json()
    session['user_id']      = u['id']
    session['username']     = u['username']
    session['display_name'] = u.get('global_name') or u['username']
    session['avatar']       = u.get('avatar')
    return redirect(next_url)


@app.route('/auth/logout')
def auth_logout():
    next_url = request.referrer or '/'
    session.clear()
    return redirect(next_url)


# ─────────────────────────────── API: assistidos ──

@app.route('/api/assistidos/<imdb_id>')
def api_assistidos(imdb_id):
    rows = _get_assistidos(imdb_id)
    for r in rows:
        r['avatar_url'] = _avatar_url(r['user_id'], r['avatar'])
    return jsonify(rows)


@app.route('/api/assistido/toggle', methods=['POST'])
def api_assistido_toggle():
    if 'user_id' not in session:
        return jsonify({'error': 'not_logged_in'}), 401
    body    = request.json or {}
    imdb_id = body.get('imdb_id')
    titulo  = body.get('titulo', '')
    if not imdb_id:
        return jsonify({'error': 'missing_imdb_id'}), 400

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM usuarios_assistidos WHERE filme_id=? AND user_id=?",
        (imdb_id, session['user_id'])
    )
    already = cursor.fetchone()

    if already:
        # Desmarca
        cursor.execute(
            "DELETE FROM usuarios_assistidos WHERE filme_id=? AND user_id=?",
            (imdb_id, session['user_id'])
        )
        watched = False
    else:
        # Marca
        cursor.execute(
            "INSERT OR IGNORE INTO usuarios_assistidos "
            "(filme_id, user_id, username, display_name, avatar, source) "
            "VALUES (?, ?, ?, ?, ?, 'manual')",
            (imdb_id, session['user_id'],
             session.get('username'), session.get('display_name'), session.get('avatar'))
        )
        # Sincroniza com listas (aparece em "Já Vistos" na home)
        cursor.execute("SELECT status FROM listas WHERE filme_id=?", (imdb_id,))
        row = cursor.fetchone()
        if row:
            if row[0] == 'watchlist':
                cursor.execute(
                    "UPDATE listas SET status='assistido' WHERE filme_id=?", (imdb_id,)
                )
        else:
            cursor.execute(
                "INSERT INTO listas (user_id, filme_id, titulo, status) "
                "VALUES (?, ?, ?, 'assistido')",
                (session['user_id'], imdb_id, titulo)
            )
        watched = True

    conn.commit()
    conn.close()
    return jsonify({'watched': watched})


# ─────────────────────────────────────────────── routes ──

@app.route('/')
def index():
    watchlist_rows, assistidos_rows = _get_db_rows()
    destaques = _pool_destaques()
    return render_template('index.html',
                           watchlist=watchlist_rows,
                           assistidos=assistidos_rows,
                           destaques=destaques)


@app.route('/filme/<imdb_id>')
def filme_page(imdb_id):
    info = get_movie(imdb_id)
    if not info:
        abort(404)
    # Check if current user has watched this film
    user_watched = False
    if 'user_id' in session:
        conn = sqlite3.connect(DB_PATH)
        user_watched = bool(conn.execute(
            "SELECT 1 FROM usuarios_assistidos WHERE filme_id=? AND user_id=?",
            (imdb_id, session['user_id'])
        ).fetchone())
        conn.close()
    return render_template('filme.html', filme=info, user_watched=user_watched)


SECOES = {
    'fila':       ('watchlist',  'Na Fila',    '#fila'),
    'vistos':     ('assistido',  'Já Vistos',  '#vistos'),
    'destaques':  (None,         'Destaques',  '#popular'),
}

@app.route('/filmes/<secao>')
def lista_completa(secao):
    if secao not in SECOES:
        abort(404)
    page  = max(1, int(request.args.get('page', 1)))
    status, titulo, _ = SECOES[secao]

    if secao == 'destaques':
        filmes, total = _pool_page(page)
        is_db = False
    else:
        rows, total = _get_db_page(status, page)
        filmes = rows
        is_db  = True

    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template('lista.html',
                           filmes=filmes, secao=secao, titulo=titulo,
                           page=page, total_pages=total_pages,
                           total=total, is_db=is_db)


@app.route('/api/filme/<imdb_id>')
def api_filme(imdb_id):
    info = get_movie(imdb_id)
    if not info:
        return jsonify({'error': 'not found'}), 404
    return jsonify(info)


if __name__ == '__main__':
    port  = int(os.environ.get('WEB_PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
