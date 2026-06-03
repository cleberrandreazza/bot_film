"""Filmes em cartaz no Brasil (JustWatch) — compartilhado site + bot."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import requests

T = TypeVar("T")

_JW_GRAPHQL = "https://apis.justwatch.com/graphql"
_JW_CARTAZ_QUERY = (
    '{ popularTitles(country: BR, first: 6,'
    ' filter: {searchQuery: "%s", objectTypes: [MOVIE]}) {'
    " edges { node { __typename ... on Movie {"
    ' content(country: BR, language: "pt") {'
    " title externalIds { imdbId }"
    " }"
    " offers(country: BR, platform: WEB) { monetizationType }"
    " } } } } }"
)
_CARTAZ_CACHE: dict[str, tuple[bool, float]] = {}
_CARTAZ_CACHE_TTL = 6 * 3600


def filme_em_cartaz_br(imdb_id: str, titulo: str, ano: str = "") -> bool:
    """True se o filme está em cartaz no Brasil (JustWatch: oferta CINEMA)."""
    key = imdb_id or f"{titulo}:{ano}"
    now = time.time()
    cached = _CARTAZ_CACHE.get(key)
    if cached and now - cached[1] < _CARTAZ_CACHE_TTL:
        return cached[0]

    busca = f"{titulo} {ano}".strip() if ano and ano != "N/A" else titulo
    safe = busca.replace('"', '\\"')
    try:
        resp = requests.post(
            _JW_GRAPHQL,
            json={"query": _JW_CARTAZ_QUERY % safe},
            headers={
                "User-Agent": "JustWatch/4.0 (Android)",
                "Content-Type": "application/json",
            },
            timeout=8,
        )
        if not resp.ok:
            return False
        edges = (resp.json().get("data") or {}).get("popularTitles", {}).get("edges", [])
        em_cartaz = False
        for edge in edges:
            node = edge.get("node", {})
            if node.get("__typename") != "Movie":
                continue
            content = node.get("content", {})
            node_imdb = (content.get("externalIds") or {}).get("imdbId", "")
            if imdb_id and node_imdb and node_imdb != imdb_id:
                continue
            for offer in node.get("offers") or []:
                if (offer.get("monetizationType") or "").upper() == "CINEMA":
                    em_cartaz = True
                    break
            if em_cartaz:
                break
        _CARTAZ_CACHE[key] = (em_cartaz, now)
        return em_cartaz
    except Exception as e:
        print(f"[Cartaz] Erro ao consultar JustWatch: {e}")
        return False


def filtrar_fora_cartaz(
    itens: list[T],
    *,
    get_filme_id: Callable[[T], str],
    get_titulo: Callable[[T], str],
    get_ano: Callable[[T], str] | None = None,
) -> tuple[list[T], list[str]]:
    """Separa itens elegíveis e títulos em cartaz."""
    ano_fn = get_ano or (lambda _: "")
    elegiveis: list[T] = []
    em_cartaz: list[str] = []
    for item in itens:
        ano = ano_fn(item)
        if ano == "N/A":
            ano = ""
        if filme_em_cartaz_br(get_filme_id(item), get_titulo(item), ano):
            em_cartaz.append(get_titulo(item))
        else:
            elegiveis.append(item)
    return elegiveis, em_cartaz
