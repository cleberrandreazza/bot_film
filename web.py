from flask import Flask, render_template, jsonify, abort
import sqlite3
import requests
import os
import time

app = Flask(__name__)

TMDB_KEY = os.environ.get('TMDB_API_KEY', '')
TMDB_BASE = 'https://api.themoviedb.org/3'
DB_PATH = '/data/filmes.db' if os.path.exists('/data') else 'filmes.db'

_cache: dict = {}
_TTL = 3600  # 1 hour


def tmdb(endpoint, params=None):
    if not TMDB_KEY:
        return None
    p = {'api_key': TMDB_KEY, 'language': 'pt-BR', **(params or {})}
    key = f"{endpoint}|{tuple(sorted(p.items()))}"
    now = time.time()
    if key in _cache and now - _cache[key][1] < _TTL:
        return _cache[key][0]
    try:
        r = requests.get(f"{TMDB_BASE}{endpoint}", params=p, timeout=8)
        if r.ok:
            data = r.json()
            _cache[key] = (data, now)
            return data
    except Exception:
        pass
    return None


def _build_movie(tmdb_id, imdb_id=None):
    details = tmdb(f'/movie/{tmdb_id}')
    if not details:
        return None

    videos   = tmdb(f'/movie/{tmdb_id}/videos') or {}
    providers = tmdb(f'/movie/{tmdb_id}/watch/providers') or {}
    credits  = tmdb(f'/movie/{tmdb_id}/credits') or {}

    # Trailer — prefer pt-BR, fallback to any YouTube trailer
    trailer = None
    trailers = [v for v in videos.get('results', [])
                if v['type'] == 'Trailer' and v['site'] == 'YouTube']
    pt = [v for v in trailers if v.get('iso_639_1') == 'pt']
    chosen = (pt or trailers or [None])[0]
    if chosen:
        trailer = chosen['key']

    # Brazil streaming
    br_data = providers.get('results', {}).get('BR', {})
    br = {
        'flatrate': br_data.get('flatrate', []),
        'rent':     br_data.get('rent', []),
        'buy':      br_data.get('buy', []),
        'link':     br_data.get('link', ''),
    }

    # Director
    director = next(
        (c['name'] for c in credits.get('crew', []) if c['job'] == 'Director'),
        None
    )

    # Cast (top 8)
    cast = [
        {
            'nome':       c['name'],
            'personagem': c['character'],
            'foto': f"https://image.tmdb.org/t/p/w185{c['profile_path']}" if c.get('profile_path') else '',
        }
        for c in credits.get('cast', [])[:8]
    ]

    release = details.get('release_date') or ''

    return {
        'imdb_id':        imdb_id or details.get('imdb_id', ''),
        'tmdb_id':        tmdb_id,
        'titulo':         details.get('title', ''),
        'titulo_original':details.get('original_title', ''),
        'sinopse':        details.get('overview') or 'Sem sinopse disponível.',
        'poster':  f"https://image.tmdb.org/t/p/w500{details['poster_path']}"   if details.get('poster_path')   else '',
        'backdrop':f"https://image.tmdb.org/t/p/w1280{details['backdrop_path']}" if details.get('backdrop_path') else '',
        'ano':     release[:4],
        'nota':    round(details.get('vote_average', 0), 1),
        'votos':   details.get('vote_count', 0),
        'duracao': details.get('runtime', 0),
        'generos': [g['name'] for g in details.get('genres', [])],
        'tagline': details.get('tagline', ''),
        'diretor': director,
        'trailer': trailer,
        'providers': br,
        'elenco':  cast,
    }


def get_by_imdb(imdb_id):
    result = tmdb(f'/find/{imdb_id}', {'external_source': 'imdb_id'})
    if not result or not result.get('movie_results'):
        return None
    return _build_movie(result['movie_results'][0]['id'], imdb_id=imdb_id)


def get_by_tmdb(tmdb_id):
    return _build_movie(int(tmdb_id))


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


# ------------------------------------------------------------------ routes ---

@app.route('/')
def index():
    watchlist_rows, assistidos_rows = _get_db_rows()

    # Trending (one API call, cached)
    trending_data = tmdb('/trending/movie/week') or {}
    trending = [
        {
            'tmdb_id': m['id'],
            'titulo':  m.get('title', ''),
            'poster':  f"https://image.tmdb.org/t/p/w500{m['poster_path']}" if m.get('poster_path') else '',
            'ano':     (m.get('release_date') or '')[:4],
            'nota':    round(m.get('vote_average', 0), 1),
        }
        for m in trending_data.get('results', [])[:12]
    ]

    return render_template('index.html',
                           watchlist=watchlist_rows,
                           assistidos=assistidos_rows,
                           trending=trending)


@app.route('/filme/<film_id>')
def filme_page(film_id):
    info = get_by_imdb(film_id) if film_id.startswith('tt') else get_by_tmdb(film_id)
    if not info:
        abort(404)
    return render_template('filme.html', filme=info)


@app.route('/api/filme/<film_id>')
def api_filme(film_id):
    info = get_by_imdb(film_id) if film_id.startswith('tt') else get_by_tmdb(film_id)
    if not info:
        return jsonify({'error': 'not found'}), 404
    return jsonify(info)


if __name__ == '__main__':
    port = int(os.environ.get('WEB_PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
