"""Lógica compartilhada do sorteio da fila (site + bot)."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TypeVar

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


def sortear_pool_e_vencedor(itens: list[T]) -> tuple[list[T], T]:
    """Amostra até SORTEIO_POOL_MAX itens aleatórios e sorteia 1 entre eles."""
    if not itens:
        raise ValueError("fila_vazia")
    pool = random.sample(itens, min(SORTEIO_POOL_MAX, len(itens)))
    return pool, random.choice(pool)


def sortear_fila(
    itens: list[T],
    filme_ids_com_evento: set[str],
    *,
    get_filme_id: Callable[[T], str],
) -> tuple[list[T], T]:
    """Filtra filmes sem evento ativo, depois sorteia pool (10) + vencedor."""
    elegiveis = filtrar_fila_sem_evento_ativo(
        itens, filme_ids_com_evento, get_filme_id=get_filme_id,
    )
    if not elegiveis:
        raise ValueError("sem_elegiveis_evento")
    return sortear_pool_e_vencedor(elegiveis)
