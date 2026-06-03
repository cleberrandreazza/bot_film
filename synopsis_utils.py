"""Sinopse em português (Wikipedia PT) com validação + fallback OMDB."""

import re
import time
import requests

_CACHE: dict[str, tuple[str | None, float]] = {}
_CACHE_TTL = 24 * 3600
_WIKI_HEADERS = {"User-Agent": "CinemaColetivo/1.0"}


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
    # Sem palavras em comum: aceita só se o ano aparecer no texto
    return bool(ano and len(ano) == 4 and ano in blob)


def _formatar_extract(extract: str) -> str:
    sentences = [s.strip() for s in extract.split(".") if s.strip()]
    synopsis = ". ".join(sentences[:4]) + "."
    if len(synopsis) > 600:
        synopsis = synopsis[:600].rsplit(" ", 1)[0] + "…"
    return synopsis


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
) -> str:
    """PT validado na Wikipedia; se falhar, sinopse OMDB (inglês, mas do IMDb certo)."""
    pt = buscar_sinopse_pt(titulo, ano, titulo_omdb)
    if pt:
        return pt
    return (sinopse_omdb or "").strip()
