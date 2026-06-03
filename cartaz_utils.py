"""Filmes em cartaz / lançamento — elegibilidade do sorteio (site + bot)."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import TypeVar

import requests

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

T = TypeVar("T")

BRT = timezone(timedelta(hours=-3))
_OMDB_KEY = os.environ.get("OMDB_API_KEY", "").strip()
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; CineBotecao/1.0)"}

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
_EXCLUIR_SORTEIO_CACHE: dict[str, tuple[bool, float]] = {}
_CACHE_TTL = 6 * 3600


def _hoje_brt() -> date:
    return datetime.now(BRT).date()


def _parse_ano(ano: str) -> int | None:
    if not ano or str(ano).strip().upper() == "N/A":
        return None
    m = re.search(r"\d{4}", str(ano))
    return int(m.group(0)) if m else None


def _fetch_omdb(imdb_id: str) -> dict | None:
    if not _OMDB_KEY or not imdb_id:
        return None
    try:
        r = requests.get(
            "https://www.omdbapi.com/",
            params={"apikey": _OMDB_KEY, "i": imdb_id},
            headers=_HTTP_HEADERS,
            timeout=8,
        )
        if r.ok:
            data = r.json()
            if data.get("Response") == "True":
                return data
    except Exception as e:
        print(f"[Cartaz] OMDB: {e}")
    return None


def _data_lancamento(imdb_id: str, ano: str) -> date | None:
    """Primeira data de lançamento conhecida (OMDB Released ou 1º/jan do ano)."""
    data = _fetch_omdb(imdb_id) if imdb_id else None
    if data:
        released = (data.get("Released") or "").strip()
        if released and released != "N/A":
            for fmt in ("%d %b %Y", "%d %B %Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(released, fmt).date()
                except ValueError:
                    continue
        year_s = (data.get("Year") or "").strip()
        y = _parse_ano(year_s)
        if y:
            return date(y, 1, 1)
    y = _parse_ano(ano)
    if y:
        return date(y, 1, 1)
    return None


def filme_ainda_nao_lancado(imdb_id: str, titulo: str, ano: str = "") -> bool:
    """True se o filme ainda não estreou (data de lançamento no futuro)."""
    hoje = _hoje_brt()
    ano_n = _parse_ano(ano)
    if ano_n and ano_n > hoje.year:
        return True
    lanc = _data_lancamento(imdb_id, ano)
    if lanc and lanc > hoje:
        return True
    return False


def filme_em_cartaz_br(imdb_id: str, titulo: str, ano: str = "") -> bool:
    """True se o filme está em cartaz no Brasil (JustWatch: oferta CINEMA)."""
    key = f"jw:{imdb_id or titulo}:{ano}"
    now = time.time()
    cached = _CARTAZ_CACHE.get(key)
    if cached and now - cached[1] < _CACHE_TTL:
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


def filme_excluir_sorteio(imdb_id: str, titulo: str, ano: str = "") -> bool:
    """
    True = não pode ser sorteado: em cartaz agora OU estreia ainda no futuro.
    (Filmes como estreias de 2026 sem oferta CINEMA passavam só pelo JustWatch.)
    """
    key = imdb_id or f"{titulo}:{ano}"
    now = time.time()
    cached = _EXCLUIR_SORTEIO_CACHE.get(key)
    if cached and now - cached[1] < _CACHE_TTL:
        return cached[0]

    excluir = filme_ainda_nao_lancado(imdb_id, titulo, ano) or filme_em_cartaz_br(
        imdb_id, titulo, ano,
    )
    _EXCLUIR_SORTEIO_CACHE[key] = (excluir, now)
    return excluir


def filtrar_fora_cartaz(
    itens: list[T],
    *,
    get_filme_id: Callable[[T], str],
    get_titulo: Callable[[T], str],
    get_ano: Callable[[T], str] | None = None,
) -> tuple[list[T], list[str]]:
    """Separa itens elegíveis e títulos excluídos (cartaz ou não lançado)."""
    ano_fn = get_ano or (lambda _: "")
    elegiveis: list[T] = []
    excluidos: list[str] = []
    for item in itens:
        ano = ano_fn(item)
        if ano == "N/A":
            ano = ""
        if filme_excluir_sorteio(get_filme_id(item), get_titulo(item), ano):
            excluidos.append(get_titulo(item))
        else:
            elegiveis.append(item)
    return elegiveis, excluidos
