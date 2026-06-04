#!/usr/bin/env python3
"""Grava hash de avatar no Convex para quem já está em usuarios_assistidos."""

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

import convex_db
from discord_profiles import buscar_perfil_usuario


def main() -> int:
    filme_id = sys.argv[1] if len(sys.argv) > 1 else "tt0091251"
    rows = convex_db.list_assistidos(filme_id)
    if not rows:
        print(f"Nenhum assistido para {filme_id}")
        return 1
    ok = 0
    for r in rows:
        uid = str(r["user_id"])
        api = buscar_perfil_usuario(uid)
        if not api or not api.get("avatar"):
            print(f"  skip {uid} (sem avatar na API)")
            continue
        convex_db.upsert_assistido(
            filme_id, uid,
            api.get("username") or r.get("username"),
            api.get("display_name") or r.get("display_name"),
            api["avatar"],
            r.get("source", "evento"),
        )
        print(f"  ok {api.get('username')} -> {api['avatar'][:12]}...")
        ok += 1
    print(f"Atualizados: {ok}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
