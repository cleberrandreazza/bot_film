"""Sinopse em português: Wikipedia PT, IMDb PT (imdb.com/pt), fallback OMDB."""

import json
import re
import time

import requests

_CACHE: dict[str, tuple[str | None, float]] = {}
_IMDB_CACHE: dict[str, tuple[str | None, float]] = {}
_CACHE_TTL = 24 * 3600

IMDB_PT_BASE = "https://www.imdb.com/pt/"
IMDB_PT_TITLE_URL = "https://www.imdb.com/pt/title/{imdb_id}/"
_IMDB_GRAPHQL = "https://api.graphql.imdb.com/"
_IMDB_PLOT_QUERY = (
    "query Plot($id: ID!) { title(id: $id) { plot { plotText { plainText } } } }"
)

_WIKI_HEADERS = {"User-Agent": "CinemaColetivo/1.0"}
_IMDB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Content-Type": "application/json",
    "X-IMDb-User-Country": "BR",
    "X-IMDb-User-Language": "pt-BR",
    "Referer": IMDB_PT_BASE,
}


def _normalizar_imdb_id(imdb_id: str) -> str:
    imdb_id = (imdb_id or "").strip().lower()
    if not imdb_id:
        return ""
    if not imdb_id.startswith("tt"):
        imdb_id = f"tt{imdb_id}"
    if re.fullmatch(r"tt\d{7,8}", imdb_id):
        return imdb_id
    return ""


def _truncar_sinopse(texto: str, max_len: int = 600) -> str:
    texto = (texto or "").strip()
    if len(texto) <= max_len:
        return texto
    cortado = texto[:max_len].rsplit(" ", 1)[0]
    return cortado + "…"


def _palavras_significativas(texto: str) -> set[str]:
    return {w.lower() for w in re.findall(r"\w{3,}", texto or "", flags=re.UNICODE)}


def _wiki_sinopse_valida(
    titulo_pagina: str,
    extract: str,
    titulos_filme: list[str],
    ano: str,
) -> bool:
    if not extract or len(extract) < 80:
        return False
    blob = f"{titulo_pagina} {extract}".lower()
    if ano and len(ano) == 4 and ano not in blob:
        return False
    palavras_pagina = _palavras_significativas(titulo_pagina)
    for titulo in titulos_filme:
        if not titulo:
            continue
        palavras_filme = _palavras_significativas(titulo)
        if palavras_filme & palavras_pagina:
            return True
    return bool(ano and len(ano) == 4 and ano in blob)


def _formatar_extract(extract: str) -> str:
    sentences = [s.strip() for s in extract.split(".") if s.strip()]
    synopsis = ". ".join(sentences[:4]) + "."
    return _truncar_sinopse(synopsis)


def _wiki_search(busca: str, limit: int = 5) -> list[dict]:
    try:
        r = requests.get(
            "https://pt.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": busca,
                "format": "json",
                "srlimit": limit,
                "utf8": 1,
            },
            headers=_WIKI_HEADERS,
            timeout=5,
        )
        if r.ok:
            return (r.json().get("query") or {}).get("search", [])
    except Exception as e:
        print(f"[Sinopse] Erro na busca Wikipedia: {e}")
    return []


def _wiki_extract(titulo_pagina: str) -> str:
    try:
        r = requests.get(
            "https://pt.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "titles": titulo_pagina,
                "format": "json",
                "utf8": 1,
            },
            headers=_WIKI_HEADERS,
            timeout=5,
        )
        if r.ok:
            pages = (r.json().get("query") or {}).get("pages", {})
            for page in pages.values():
                return (page.get("extract") or "").strip()
    except Exception as e:
        print(f"[Sinopse] Erro ao ler Wikipedia: {e}")
    return ""


def _imdb_plot_graphql(imdb_id: str) -> str:
    try:
        r = requests.post(
            _IMDB_GRAPHQL,
            json={"query": _IMDB_PLOT_QUERY, "variables": {"id": imdb_id}},
            headers=_IMDB_HEADERS,
            timeout=10,
        )
        if not r.ok:
            return ""
        data = r.json()
        plot = (
            (data.get("data") or {})
            .get("title", {})
            .get("plot", {})
            .get("plotText", {})
            .get("plainText", "")
        )
        return (plot or "").strip()
    except Exception as e:
        print(f"[Sinopse] Erro IMDb PT ({imdb_id}): {e}")
    return ""


def _imdb_plot_html(imdb_id: str) -> str:
    """Fallback: página PT do título (JSON-LD / __NEXT_DATA__)."""
    url = IMDB_PT_TITLE_URL.format(imdb_id=imdb_id)
    try:
        r = requests.get(
            url,
            headers={k: v for k, v in _IMDB_HEADERS.items() if k != "Content-Type"},
            timeout=12,
        )
        if r.status_code != 200 or len(r.text) < 500:
            return ""
        for block in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            r.text,
            flags=re.DOTALL,
        ):
            try:
                payload = json.loads(block)
            except json.JSONDecodeError:
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                desc = (item.get("description") or "").strip()
                if len(desc) >= 40:
                    return desc
        m = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text,
            re.DOTALL,
        )
        if m:
            blob = m.group(1)
            for match in re.finditer(r'"plainText"\s*:\s*"((?:\\.|[^"\\])*)"', blob):
                text = json.loads(f'"{match.group(1)}"')
                if len(text) >= 40:
                    return text.strip()
    except Exception as e:
        print(f"[Sinopse] Erro scrape IMDb PT ({imdb_id}): {e}")
    return ""


def buscar_sinopse_imdb_pt(imdb_id: str) -> str | None:
    """
    Sinopse em português do IMDb (locale PT-BR, equivalente a imdb.com/pt).
    Usa GraphQL com cabeçalhos de localização; fallback leve na URL PT do título.
    """
    imdb_id = _normalizar_imdb_id(imdb_id)
    if not imdb_id:
        return None

    now = time.time()
    cached = _IMDB_CACHE.get(imdb_id)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]

    plot = _imdb_plot_graphql(imdb_id)
    if len(plot) < 30:
        plot = _imdb_plot_html(imdb_id)
    if len(plot) < 30:
        _IMDB_CACHE[imdb_id] = (None, now)
        return None

    synopsis = _truncar_sinopse(plot)
    _IMDB_CACHE[imdb_id] = (synopsis, now)
    return synopsis


def buscar_sinopse_pt(
    titulo: str,
    ano: str = "",
    titulo_alt: str = "",
) -> str | None:
    """
    Sinopse em português via Wikipedia PT.
    Valida ano e título para não pegar artigo errado (ex.: outro filme).
    """
    titulo = (titulo or "").strip()
    titulo_alt = (titulo_alt or "").strip()
    ano = (ano or "").strip()
    if ano == "N/A":
        ano = ""

    key = f"{titulo}|{titulo_alt}|{ano}"
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]

    titulos_ref = [t for t in (titulo, titulo_alt) if t]
    queries: list[str] = []
    if titulo and ano:
        queries.append(f"{titulo} {ano} filme")
    if titulo_alt and titulo_alt != titulo and ano:
        queries.append(f"{titulo_alt} {ano} filme")
    if titulo:
        queries.append(f"{titulo} filme")
    if titulo_alt and titulo_alt != titulo:
        queries.append(f"{titulo_alt} filme")

    vistos: set[str] = set()
    for busca in queries:
        for hit in _wiki_search(busca):
            pagina = hit.get("title", "")
            if not pagina or pagina in vistos:
                continue
            vistos.add(pagina)
            extract = _wiki_extract(pagina)
            if _wiki_sinopse_valida(pagina, extract, titulos_ref, ano):
                synopsis = _formatar_extract(extract)
                _CACHE[key] = (synopsis, now)
                return synopsis

    _CACHE[key] = (None, now)
    return None


def sinopse_para_filme(
    titulo: str,
    ano: str,
    titulo_omdb: str = "",
    sinopse_omdb: str = "",
    imdb_id: str = "",
) -> str:
    """
    Ordem: Wikipedia PT (validada) → IMDb PT (imdb.com/pt) → OMDB Plot.
    """
    pt = buscar_sinopse_pt(titulo, ano, titulo_omdb)
    if pt:
        return pt
    imdb_pt = buscar_sinopse_imdb_pt(imdb_id)
    if imdb_pt:
        return imdb_pt
    return (sinopse_omdb or "").strip()
