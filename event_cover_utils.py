"""Capa de evento Discord: backdrop TMDB + recorte para faixa horizontal."""

import io
import os
import time

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore


def _tmdb_api_key() -> str:
    return os.environ.get("TMDB_API_KEY", "").strip()
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w1280"

_EVENT_COVER_MAX_BYTES = 8 * 1024 * 1024
_COVER_ASPECT = 550 / 120  # faixa visível no card do Discord
_COVER_WIDTH = 1100
_COVER_HEIGHT = round(_COVER_WIDTH / _COVER_ASPECT)

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_TMDB_CACHE: dict[str, tuple[str | None, float]] = {}
_BYTES_CACHE: dict[str, tuple[bytes | None, float]] = {}
_CACHE_TTL = 24 * 3600


def _cache_get(store: dict, key: str) -> str | bytes | None:
    entry = store.get(key)
    if entry and time.time() - entry[1] < _CACHE_TTL:
        return entry[0]
    return None


def _cache_set(store: dict, key: str, value: str | bytes | None) -> None:
    store[key] = (value, time.time())


def _tmdb_get(path: str, params: dict | None = None) -> dict | list | None:
    api_key = _tmdb_api_key()
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
        print(f"[Capa evento] TMDB {path}: {e}")
    return None


def _melhor_backdrop_path(imdb_id: str) -> str | None:
    cached = _cache_get(_TMDB_CACHE, imdb_id)
    if cached is not None:
        return cached or None

    path: str | None = None
    data = _tmdb_get(f"/find/{imdb_id}", {"external_source": "imdb_id"})
    if not data:
        _cache_set(_TMDB_CACHE, imdb_id, None)
        return None

    media = None
    media_type = ""
    for kind, mtype in (("movie_results", "movie"), ("tv_results", "tv")):
        results = data.get(kind) or []
        if results:
            media = results[0]
            media_type = mtype
            break

    if not media:
        _cache_set(_TMDB_CACHE, imdb_id, None)
        return None

    path = (media.get("backdrop_path") or "").strip() or None
    tmdb_id = media.get("id")
    if not path and tmdb_id and media_type:
        images = _tmdb_get(f"/{media_type}/{tmdb_id}/images")
        if images:
            backdrops = images.get("backdrops") or []
            if backdrops:
                best = max(
                    backdrops,
                    key=lambda b: (
                        float(b.get("vote_average") or 0),
                        int(b.get("width") or 0),
                    ),
                )
                path = (best.get("file_path") or "").strip() or None

    _cache_set(_TMDB_CACHE, imdb_id, path or "")
    return path


def _baixar_bytes(url: str) -> bytes | None:
    if not url:
        return None
    try:
        r = requests.get(url, headers=_HTTP_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.content
        if not data or len(data) > _EVENT_COVER_MAX_BYTES:
            return None
        return data
    except Exception as e:
        print(f"[Capa evento] Download: {e}")
    return None


def _recortar_para_banner(raw: bytes) -> bytes | None:
    if not Image:
        print("[Capa evento] Pillow não instalado; enviando imagem sem recorte.")
        return raw
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        w, h = img.size
        if w < 2 or h < 2:
            return None
        current = w / h
        if current > _COVER_ASPECT:
            new_w = int(h * _COVER_ASPECT)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / _COVER_ASPECT)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
        img = img.resize((_COVER_WIDTH, _COVER_HEIGHT), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88, optimize=True)
        data = out.getvalue()
        if len(data) > _EVENT_COVER_MAX_BYTES:
            return None
        return data
    except Exception as e:
        print(f"[Capa evento] Recorte: {e}")
    return None


def preparar_capa_evento(imdb_id: str, poster_url: str = "") -> bytes | None:
    """
    Capa horizontal para scheduled event: backdrop TMDB (16:9) recortado ~550:120.
    Fallback: poster IMDb/OMDB com o mesmo recorte.
    """
    imdb_id = (imdb_id or "").strip()
    cache_key = f"cover:{imdb_id}"
    cached = _cache_get(_BYTES_CACHE, cache_key)
    if cached is not None:
        return cached if cached else None

    urls: list[str] = []
    backdrop = _melhor_backdrop_path(imdb_id) if imdb_id and _tmdb_api_key() else None
    if backdrop:
        urls.append(f"{TMDB_IMAGE_BASE}{backdrop}")
    if poster_url:
        urls.append(poster_url)

    result: bytes | None = None
    for url in urls:
        raw = _baixar_bytes(url)
        if not raw:
            continue
        result = _recortar_para_banner(raw)
        if result:
            break

    _cache_set(_BYTES_CACHE, cache_key, result or b"")
    return result
