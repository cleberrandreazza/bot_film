"""Lógica compartilhada do sorteio da fila (site + bot)."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TypeVar

from cartaz_utils import filtrar_fora_cartaz

SORTEIO_POOL_MAX = 10

T = TypeVar("T")


def filtrar_fila_sem_evento_ativo(
    itens: list[T],
    filme_ids_com_evento: set[str],
    *,
    get_filme_id: Callable[[T], str],
) -> list[T]:
    """Remove filmes que já têm evento agendado/ativo no Discord."""
    if not filme_ids_com_evento:
        return list(itens)
    bloqueados = filme_ids_com_evento
    return [item for item in itens if get_filme_id(item) not in bloqueados]


def amostrar_pool_sorteio(
    itens: list[T],
    filme_ids_com_evento: set[str],
    *,
    get_filme_id: Callable[[T], str],
) -> list[T]:
    """Até 10 filmes aleatórios da fila, sem consultar cartaz (rápido)."""
    elegiveis = filtrar_fila_sem_evento_ativo(
        itens, filme_ids_com_evento, get_filme_id=get_filme_id,
    )
    if not elegiveis:
        raise ValueError("sem_elegiveis_evento")
    n = min(SORTEIO_POOL_MAX, len(elegiveis))
    if len(elegiveis) <= n:
        return list(elegiveis)
    return random.sample(elegiveis, n)


def sortear_pool_e_vencedor(itens: list[T]) -> tuple[list[T], T]:
    """Sorteia 1 vencedor entre os itens (lista já filtrada)."""
    if not itens:
        raise ValueError("fila_vazia")
    return list(itens), random.choice(itens)


def sortear_fila_bot(
    itens: list[T],
    filme_ids_com_evento: set[str],
    *,
    get_filme_id: Callable[[T], str],
    get_titulo: Callable[[T], str],
    get_ano: Callable[[T], str] | None = None,
) -> tuple[list[T], T]:
    """Bot: amostra 10, verifica cartaz só nesses, escolhe vencedor."""
    pool = amostrar_pool_sorteio(
        itens, filme_ids_com_evento, get_filme_id=get_filme_id,
    )
    elegiveis, _em_cartaz = filtrar_fora_cartaz(
        pool,
        get_filme_id=get_filme_id,
        get_titulo=get_titulo,
        get_ano=get_ano,
    )
    if not elegiveis:
        raise ValueError("todos_em_cartaz")
    return sortear_pool_e_vencedor(elegiveis)
