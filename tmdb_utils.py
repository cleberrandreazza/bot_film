"""Cliente TMDB compartilhado (pt-BR): sinopse, gêneros, resolução por imdb_id."""

import os
import re
import time

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w1280"
_CACHE_TTL = 24 * 3600
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

_MEDIA_CACHE: dict[str, tuple[str, float]] = {}
_SINOPSE_CACHE: dict[str, tuple[str | None, float]] = {}


def tmdb_api_key() -> str:
    return os.environ.get("TMDB_API_KEY", "").strip()


def normalizar_imdb_id(imdb_id: str) -> str:
    imdb_id = (imdb_id or "").strip().lower()
    if not imdb_id:
        return ""
    if not imdb_id.startswith("tt"):
        imdb_id = f"tt{imdb_id}"
    if re.fullmatch(r"tt\d{7,8}", imdb_id):
        return imdb_id
    return ""


def _cache_get(store: dict, key: str):
    entry = store.get(key)
    if entry and time.time() - entry[1] < _CACHE_TTL:
        return entry[0]
    return None


def _cache_set(store: dict, key: str, value) -> None:
    store[key] = (value, time.time())


def tmdb_get(path: str, params: dict | None = None) -> dict | list | None:
    api_key = tmdb_api_key()
    if not api_key:
        return None
    try:
        r = requests.get(
            f"{TMDB_BASE}{path}",
            params={**(params or {}), "api_key": api_key},
            headers=_HTTP_HEADERS,
            timeout=10,
        )
        if r.ok:
            return r.json()
    except Exception as e:
        print(f"[TMDB] Erro {path}: {e}")
    return None


def resolver_media_por_imdb(imdb_id: str) -> tuple[str, int] | None:
    """Retorna (movie|tv, tmdb_id) a partir do imdb_id."""
    imdb_id = normalizar_imdb_id(imdb_id)
    if not imdb_id:
        return None

    cached = _cache_get(_MEDIA_CACHE, imdb_id)
    if cached is not None:
        if not cached:
            return None
        mtype, _, tid = cached.partition(":")
        return mtype, int(tid)

    data = tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
    if not data:
        _cache_set(_MEDIA_CACHE, imdb_id, "")
        return None

    for kind, mtype in (("movie_results", "movie"), ("tv_results", "tv")):
        results = data.get(kind) or []
        if results:
            mid = results[0].get("id")
            if mid:
                _cache_set(_MEDIA_CACHE, imdb_id, f"{mtype}:{mid}")
                return mtype, int(mid)

    _cache_set(_MEDIA_CACHE, imdb_id, "")
    return None


def _truncar_sinopse(texto: str, max_len: int = 600) -> str:
    texto = (texto or "").strip()
    if len(texto) <= max_len:
        return texto
    cortado = texto[:max_len].rsplit(" ", 1)[0]
    return cortado + "…"


def buscar_sinopse_tmdb_pt(imdb_id: str) -> str | None:
    """Sinopse em português (overview) via TMDB pt-BR."""
    imdb_id = normalizar_imdb_id(imdb_id)
    if not imdb_id or not tmdb_api_key():
        return None

    cached = _cache_get(_SINOPSE_CACHE, imdb_id)
    if cached is not None:
        return cached

    resultado: str | None = None
    media = resolver_media_por_imdb(imdb_id)
    if media:
        mtype, tmdb_id = media
        data = tmdb_get(f"/{mtype}/{tmdb_id}", {"language": "pt-BR"})
        if data:
            overview = (data.get("overview") or "").strip()
            if len(overview) >= 30:
                resultado = _truncar_sinopse(overview)

    _cache_set(_SINOPSE_CACHE, imdb_id, resultado)
    return resultado
