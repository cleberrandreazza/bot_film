#!/usr/bin/env python3
"""Recupera Assistido Por a partir de participantes de evento encerrado.

Uso:
  python scripts/sync_evento_assistidos.py tt0091259
  python scripts/sync_evento_assistidos.py --titulo "Come and See"
  python scripts/sync_evento_assistidos.py --todos-encerrados
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if (ROOT / ".env.local").exists():
        load_dotenv(ROOT / ".env.local")
except ModuleNotFoundError:
    pass

from evento_sync import recuperar_filme_por_id, sincronizar_eventos_encerrados  # noqa: E402
import convex_db  # noqa: E402


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _filme_id_por_titulo(needle: str) -> str | None:
    n = _norm(needle)
    for status in ("assistido", "watchlist"):
        for row in convex_db.list_by_status(status) or []:
            if n in _norm(row.get("titulo") or ""):
                return row.get("filme_id")
    for ev in convex_db.list_eventos_by_status("encerrado"):
        if n in _norm(ev.get("titulo") or ""):
            return ev.get("filme_id")
    for ev in convex_db.list_eventos_by_status("agendado"):
        if n in _norm(ev.get("titulo") or ""):
            return ev.get("filme_id")
    for ev in convex_db.list_eventos_by_status("ativo"):
        if n in _norm(ev.get("titulo") or ""):
            return ev.get("filme_id")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Assistido Por from event participants")
    parser.add_argument("filme_id", nargs="?", help="IMDb id, ex.: tt0091259")
    parser.add_argument("--titulo", "-t", help="Busca por substring no título")
    parser.add_argument(
        "--todos-encerrados", action="store_true",
        help="Sincroniza todos os eventos encerrados com participantes faltando",
    )
    args = parser.parse_args()

    if args.todos_encerrados:
        import asyncio

        async def _noop_upsert(*_a, **_k):
            pass

        total = asyncio.run(sincronizar_eventos_encerrados(lambda _g: None, _noop_upsert))
        print(f"Total inseridos em Assistido Por: {total}")
        return 0

    filme_id = args.filme_id
    if args.titulo:
        filme_id = _filme_id_por_titulo(args.titulo)
        if not filme_id:
            print(f"Filme não encontrado para título: {args.titulo!r}")
            return 1

    if not filme_id:
        parser.print_help()
        return 1

    res = recuperar_filme_por_id(filme_id)
    print(f"Filme: {res.get('titulo')} ({res.get('filme_id')})")
    if not res.get("ok"):
        print(f"Erro: {res.get('erro')}")
        return 1
    print(f"Evento Discord: {res.get('event_id')}")
    print(f"Participantes: {len(res.get('participantes') or [])}")
    for p in res.get("participantes") or []:
        print(f"  - {p.get('username') or p.get('user_id')} ({p.get('user_id')})")
    print(f"Novos registros em Assistido Por: {res.get('inseridos', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
