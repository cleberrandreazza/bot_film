from flask import Flask, render_template, jsonify, abort, request, session, redirect, url_for, send_from_directory
import random
import requests
import re
import os
import time
import urllib.parse

import convex_db
from discord_guild import invalidar_cache_usuario, usuario_e_cinefilo
from evento_service import criar_evento_agendado, opcoes_picker_evento
from cartaz_utils import filme_em_cartaz_br
from sorteio_utils import amostrar_pool_sorteio
from synopsis_utils import sinopse_para_filme

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)

OMDB_KEY             = os.environ.get('OMDB_API_KEY', '')
DISCORD_CLIENT_ID    = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET= os.environ.get('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI = os.environ.get('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/callback')

_cache: dict = {}
_TTL = 3600  # 1 hour


def _avatar_url(user_id: str, avatar: str | None) -> str:
    """Avatar Discord; IDs não numéricos (ex.: legado 'anon') usam avatar padrão."""
    if user_id.isdigit():
        if avatar:
            return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png?size=64"
        idx = (int(user_id) >> 22) % 6
        return f"https://cdn.discordapp.com/embed/avatars/{idx}.png"
    return "https://cdn.discordapp.com/embed/avatars/0.png"


@app.context_processor
def inject_user():
    u = None
    pode_sorteio = False
    if 'user_id' in session:
        uid = session['user_id']
        u = {
            'user_id':      uid,
            'username':     session.get('username', ''),
            'display_name': session.get('display_name', session.get('username', '')),
            'avatar':       session.get('avatar'),
            'avatar_url':   _avatar_url(uid, session.get('avatar')),
        }
        pode_sorteio = usuario_e_cinefilo(
            uid, session.get('discord_access_token'),
        )
    return {'current_user': u, 'pode_sorteio': pode_sorteio}


def _json_cinefilo_required():
    if 'user_id' not in session:
        return jsonify({'error': 'not_logged_in'}), 401
    if not usuario_e_cinefilo(
        session['user_id'], session.get('discord_access_token'),
    ):
        return jsonify({'error': 'sem_permissao'}), 403
    return None

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


def get_pt_synopsis(
    title: str,
    year: str,
    title_omdb: str = "",
    sinopse_omdb: str = "",
    imdb_id: str = "",
) -> str:
    """Sinopse PT: Wikipedia → IMDb PT → texto OMDB."""
    return sinopse_para_filme(title, year, title_omdb, sinopse_omdb, imdb_id)


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
        omdb_title = (data.get('Title') or '').strip()
        if omdb_title.upper() == 'N/A':
            omdb_title = ''
        movie['sinopse'] = get_pt_synopsis(
            movie['titulo'],
            movie['ano'],
            omdb_title,
            movie['sinopse'],
            imdb_id,
        )
        movie['trailer_id'] = get_trailer_id(movie['titulo'], movie['ano'])
    return movie


def search_imdb_movies(query: str, limit: int = 12) -> list[dict]:
    """Busca filmes por texto no endpoint de sugestão do IMDb."""
    query = (query or '').strip()
    if not query:
        return []
    key = f'imdb-search:{query.lower()}:{limit}'
    now = time.time()
    if key in _cache and now - _cache[key][1] < 300:
        return _cache[key][0]

    url = f"https://v3.sg.media-imdb.com/suggestion/x/{requests.utils.quote(query.lower())}.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    results: list[dict] = []
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        if not resp.ok:
            return []
        data = resp.json()
        for item in data.get('d', []):
            if item.get('q') not in {'feature', 'TV movie', 'TV series', 'video'}:
                continue
            imdb_id = item.get('id', '')
            title = item.get('l', '')
            if not imdb_id or not title:
                continue
            poster = ''
            image_info = item.get('i')
            if isinstance(image_info, dict):
                poster = image_info.get('imageUrl', '') or ''
            results.append({
                'id': imdb_id,
                'titulo': title,
                'ano': item.get('y', ''),
                'poster': poster,
            })
            if len(results) >= limit:
                break
    except Exception as e:
        print(f'IMDb search error: {e}')

    _cache[key] = (results, now)
    return results


PER_PAGE = 12


def _get_db_rows():
    try:
        watchlist  = convex_db.list_by_status('watchlist')
        assistidos = convex_db.list_by_status('assistido')
        return list(watchlist), list(assistidos)
    except Exception:
        return [], []


def _get_db_page(status: str, page: int):
    """Retorna (rows, total) paginado para uma seção do DB."""
    offset = (page - 1) * PER_PAGE
    try:
        rows, total = convex_db.list_by_status_paginated(status, PER_PAGE, offset)
        return list(rows), total
    except Exception:
        return [], 0


def _enrich_rows(rows) -> list[dict]:
    enriched = []
    for row in rows:
        item = dict(row)
        basic = _omdb_basic(item.get("filme_id", ""))
        item["poster"] = basic["poster"] if basic else ""
        item["ano"] = basic["ano"] if basic else ""
        enriched.append(item)
    return enriched


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


# ─────────────────────────────── helpers ──

def _get_assistidos(imdb_id: str) -> list:
    try:
        return convex_db.list_assistidos(imdb_id)
    except Exception:
        return []


def _get_adicionado_por(imdb_id: str) -> dict | None:
    try:
        row = convex_db.get_adicionado_por(imdb_id)
    except Exception:
        return None
    if not row:
        return None
    row['avatar_url'] = _avatar_url(row['user_id'], row.get('avatar'))
    return row


def _session_profile() -> dict:
    if 'user_id' not in session:
        return {}
    return {
        'username': session.get('username'),
        'display_name': session.get('display_name'),
        'avatar': session.get('avatar'),
    }


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
        'scope':        'identify guilds.members.read',
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
    invalidar_cache_usuario(u['id'])
    session['user_id']      = u['id']
    session['username']     = u['username']
    session['display_name'] = u.get('global_name') or u['username']
    session['avatar']       = u.get('avatar')
    session['discord_access_token'] = token
    return redirect(next_url)


@app.route('/auth/logout')
def auth_logout():
    next_url = request.args.get('next') or request.referrer or '/'
    if not next_url.startswith('/'):
        next_url = '/'
    if 'user_id' in session:
        invalidar_cache_usuario(session['user_id'])
    session.pop('discord_access_token', None)
    session.clear()
    return redirect(next_url)


# ─────────────────────────────── API: assistidos ──

@app.route('/api/assistidos/<imdb_id>')
def api_assistidos(imdb_id):
    rows = _get_assistidos(imdb_id)
    for r in rows:
        r['avatar_url'] = _avatar_url(r['user_id'], r['avatar'])
    return jsonify(rows)


@app.route('/api/fila/adicionado-por/<imdb_id>')
def api_adicionado_por(imdb_id):
    row = _get_adicionado_por(imdb_id)
    if not row:
        return jsonify(None)
    return jsonify(row)


@app.route('/api/assistido/toggle', methods=['POST'])
def api_assistido_toggle():
    if 'user_id' not in session:
        return jsonify({'error': 'not_logged_in'}), 401
    body    = request.json or {}
    imdb_id = body.get('imdb_id')
    titulo  = body.get('titulo', '')
    if not imdb_id:
        return jsonify({'error': 'missing_imdb_id'}), 400

    user_id = session['user_id']
    already = convex_db.exists_assistido(imdb_id, user_id)

    if already:
        # Desmarca
        convex_db.remove_assistido(imdb_id, user_id)
        watched = False
    else:
        # Marca
        convex_db.add_assistido(
            imdb_id, user_id,
            session.get('username'), session.get('display_name'),
            session.get('avatar'), 'manual',
        )
        # Sincroniza com listas (aparece em "Já Vistos" na home)
        convex_db.marcar_assistido(
            user_id, imdb_id, titulo, **_session_profile(),
        )
        watched = True

    return jsonify({'watched': watched})


@app.route('/api/fila/adicionar', methods=['POST'])
def api_fila_adicionar():
    if 'user_id' not in session:
        return jsonify({'error': 'not_logged_in'}), 401
    body    = request.json or {}
    imdb_id = body.get('imdb_id')
    titulo  = body.get('titulo', '')
    if not imdb_id:
        return jsonify({'error': 'missing_imdb_id'}), 400

    user_id = session['user_id']

    if convex_db.exists_assistido(imdb_id, user_id):
        return jsonify({'error': 'already_watched'}), 403

    res = convex_db.adicionar_fila(
        user_id, imdb_id, titulo, **_session_profile(),
    )
    if res.get('already'):
        return jsonify({'in_fila': True, 'already': True})
    return jsonify({'in_fila': True})


@app.route('/api/fila/remover', methods=['POST'])
def api_fila_remover():
    if 'user_id' not in session:
        return jsonify({'error': 'not_logged_in'}), 401
    body    = request.json or {}
    imdb_id = body.get('imdb_id')
    if not imdb_id:
        return jsonify({'error': 'missing_imdb_id'}), 400

    status = convex_db.get_status_by_filme(imdb_id)
    if status != 'watchlist':
        return jsonify({'error': 'not_in_fila'}), 400

    convex_db.remove_by_filme_status(imdb_id, 'watchlist')
    return jsonify({'in_fila': False})


def _fila_para_json() -> list[dict]:
    """Lista completa da watchlist enriquecida (poster/ano) para o sorteio."""
    try:
        rows = convex_db.list_by_status('watchlist')
    except Exception:
        return []
    out = []
    for row in _enrich_rows(rows):
        out.append({
            'filme_id': row.get('filme_id', ''),
            'titulo': row.get('titulo', ''),
            'poster': row.get('poster', '') or '',
            'ano': row.get('ano', '') or '',
        })
    return [f for f in out if f['filme_id']]


@app.route('/api/fila')
def api_fila_lista():
    filmes = _fila_para_json()
    return jsonify({'filmes': filmes, 'count': len(filmes)})


@app.route('/api/fila/sorteio', methods=['POST'])
def api_fila_sorteio():
    denied = _json_cinefilo_required()
    if denied:
        return denied
    filmes = _fila_para_json()
    if not filmes:
        return jsonify({'error': 'fila_vazia'}), 400
    try:
        bloqueados = convex_db.filme_ids_com_evento_ativo()
        pool = amostrar_pool_sorteio(
            filmes,
            bloqueados,
            get_filme_id=lambda f: f.get('filme_id', ''),
        )
    except ValueError as e:
        if str(e) == 'sem_elegiveis_evento':
            return jsonify({
                'error': 'sem_elegiveis_evento',
                'message': (
                    'Nenhum filme elegível para sortear (todos com sessão '
                    'agendada/ativa no Discord).'
                ),
            }), 400
        raise
    return jsonify({'pool': pool, 'pool_size': len(pool)})


@app.route('/api/fila/em-cartaz', methods=['POST'])
def api_fila_em_cartaz():
    """Verifica um filme no JustWatch (usado durante a animação do sorteio)."""
    denied = _json_cinefilo_required()
    if denied:
        return denied
    body = request.json or {}
    filme_id = (body.get('filme_id') or '').strip()
    titulo = (body.get('titulo') or '').strip()
    ano = str(body.get('ano') or '').strip()
    if not filme_id and not titulo:
        return jsonify({'error': 'dados_invalidos'}), 400
    em_cartaz = filme_em_cartaz_br(filme_id, titulo or 'Filme', ano)
    return jsonify({'em_cartaz': em_cartaz})


@app.route('/api/evento/opcoes')
def api_evento_opcoes():
    denied = _json_cinefilo_required()
    if denied:
        return denied
    return jsonify(opcoes_picker_evento())


@app.route('/api/evento/criar', methods=['POST'])
def api_evento_criar():
    denied = _json_cinefilo_required()
    if denied:
        return denied
    body = request.json or {}
    filme_id = (body.get('filme_id') or '').strip()
    titulo = (body.get('titulo') or '').strip()
    data = (body.get('data') or '').strip()
    hora = (body.get('hora') or '').strip()
    capa_url = (body.get('poster') or body.get('capa_url') or '').strip()
    ano = (body.get('ano') or '').strip()
    if not filme_id or not titulo:
        return jsonify({'error': 'dados_invalidos'}), 400
    if not data or not hora:
        return jsonify({'error': 'data_hora_obrigatorias'}), 400

    resultado, erro = criar_evento_agendado(
        filme_id, titulo, capa_url, data, hora, ano_imdb=ano,
    )
    if erro:
        return jsonify({'error': 'criar_falhou', 'message': erro}), 400
    return jsonify({'ok': True, **resultado})


# ─────────────────────────────────────────────── routes ──

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(app.static_folder, 'favicon.png', mimetype='image/png')


@app.route('/')
def index():
    watchlist_rows, assistidos_rows = _get_db_rows()
    return render_template('index.html',
                           watchlist=_enrich_rows(watchlist_rows),
                           assistidos=_enrich_rows(assistidos_rows))


@app.route('/filme/<imdb_id>')
def filme_page(imdb_id):
    info = get_movie(imdb_id)
    if not info:
        # Fallback: monta info mínima a partir da listas
        try:
            titulo = convex_db.get_titulo_by_filme(imdb_id)
        except Exception:
            titulo = None
        if not titulo:
            abort(404)
        info = {
            'imdb_id': imdb_id, 'titulo': titulo, 'poster': '',
            'ano': '', 'nota': '', 'sinopse': '', 'duracao': None,
            'diretor': '', 'generos': [], 'elenco': [], 'rated': '',
            'pais': '', 'ratings': {}, 'streaming': [], 'trailer_id': '',
        }
    user_watched = False
    in_fila      = False
    if 'user_id' in session:
        user_watched = convex_db.exists_assistido(imdb_id, session['user_id'])
    in_fila = convex_db.get_status_by_filme(imdb_id) == 'watchlist'
    return render_template('filme.html', filme=info,
                           user_watched=user_watched, in_fila=in_fila)


SECOES = {
    'fila':   ('watchlist',  'Na Fila',   '#fila'),
    'vistos': ('assistido',  'Já Vistos', '#vistos'),
}

@app.route('/filmes/<secao>')
def lista_completa(secao):
    if secao not in SECOES:
        abort(404)
    page  = max(1, int(request.args.get('page', 1)))
    status, titulo, _ = SECOES[secao]
    rows, total = _get_db_page(status, page)
    total = int(total)
    filmes = _enrich_rows(rows)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    return render_template('lista.html',
                           filmes=filmes, secao=secao, titulo=titulo,
                           page=page, total_pages=total_pages,
                           total=total, is_db=True)


@app.route('/api/filme/<imdb_id>')
def api_filme(imdb_id):
    info = get_movie(imdb_id)
    if not info:
        return jsonify({'error': 'not found'}), 404
    return jsonify(info)


@app.route('/api/busca')
def api_busca():
    query = (request.args.get('q') or '').strip()
    if len(query) < 2:
        return jsonify({'items': [], 'error': 'query_too_short'}), 400
    items = search_imdb_movies(query, limit=12)
    return jsonify({'items': items})


@app.route('/buscar')
def busca_page():
    query = (request.args.get('q') or '').strip()
    resultados = search_imdb_movies(query, limit=24) if len(query) >= 2 else []
    return render_template('busca.html', query=query, resultados=resultados)


if __name__ == '__main__':
    port  = int(os.environ.get('PORT', os.environ.get('WEB_PORT', 5000)))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
