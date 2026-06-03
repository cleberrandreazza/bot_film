#!/usr/bin/env python3
"""Popula Convex para testar sorteio: assistidos + 60 filmes na fila.

Uso (na raiz do projeto):
  python scripts/seed_sorteio_teste.py
  python scripts/seed_sorteio_teste.py --limpar-fila
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import convex_db  # noqa: E402

SEED_USER = "seed-cinefilo"
SEED_DISPLAY = "Seed Teste"

ASSISTIDOS = [
    ("tt0111161", "The Shawshank Redemption"),
    ("tt0068646", "The Godfather"),
    ("tt0071562", "The Godfather Part II"),
    ("tt0468569", "The Dark Knight"),
    ("tt0050083", "12 Angry Men"),
    ("tt0108052", "Schindler's List"),
    ("tt0167260", "The Lord of the Rings: The Return of the King"),
    ("tt0110912", "Pulp Fiction"),
    ("tt0060196", "The Good, the Bad and the Ugly"),
    ("tt0137523", "Fight Club"),
    ("tt0109830", "Forrest Gump"),
    ("tt1375666", "Inception"),
    ("tt0167261", "The Lord of the Rings: The Two Towers"),
    ("tt0080684", "Star Wars: Episode V - The Empire Strikes Back"),
    ("tt0133093", "The Matrix"),
    ("tt0099685", "Goodfellas"),
    ("tt0073486", "One Flew Over the Cuckoo's Nest"),
    ("tt0114369", "Se7en"),
    ("tt0038650", "It's a Wonderful Life"),
    ("tt0047478", "Seven Samurai"),
    ("tt0102926", "The Silence of the Lambs"),
    ("tt0317248", "City of God"),
    ("tt0118799", "Life Is Beautiful"),
    ("tt0076759", "Star Wars"),
    ("tt0120815", "Saving Private Ryan"),
    ("tt0816692", "Interstellar"),
    ("tt0120689", "The Green Mile"),
    ("tt0253474", "The Pianist"),
    ("tt0407887", "The Departed"),
    ("tt0172495", "Gladiator"),
    ("tt0482571", "The Prestige"),
    ("tt0993846", "The Wolf of Wall Street"),
    ("tt7286456", "Joker"),
    ("tt1856101", "Blade Runner 2049"),
    ("tt9362722", "Spider-Man: Across the Spider-Verse"),
]

FILA_60 = [
    ("tt0910970", "WALL·E"),
    ("tt1049413", "Up"),
    ("tt0435765", "Toy Story 3"),
    ("tt2380307", "Coco"),
    ("tt2262227", "The Tale of The Princess Kaguya"),
    ("tt1951266", "The Wind Rises"),
    ("tt0347149", "Howl's Moving Castle"),
    ("tt0096283", "My Neighbor Totoro"),
    ("tt1798709", "Her"),
    ("tt2582802", "Whiplash"),
    ("tt5362988", "Wolf Children"),
    ("tt5311514", "Your Name"),
    ("tt5323662", "A Silent Voice"),
    ("tt3900578", "The Handmaiden"),
    ("tt6751668", "Parasite"),
    ("tt1187043", "3 Idiots"),
    ("tt5074352", "Dangal"),
    ("tt1636826", "PK"),
    ("tt0457433", "Pan's Labyrinth"),
    ("tt0361748", "Inglourious Basterds"),
    ("tt1028532", "Hachi: A Dog's Tale"),
    ("tt0095016", "Die Hard"),
    ("tt0114709", "Toy Story"),
    ("tt0110357", "The Lion King"),
    ("tt0126029", "Shrek"),
    ("tt0266543", "Finding Nemo"),
    ("tt0382932", "Ratatouille"),
    ("tt0317705", "The Incredibles"),
    ("tt2096673", "Inside Out"),
    ("tt3606756", "Incredibles 2"),
    ("tt1490017", "The Lego Movie"),
    ("tt1438176", "Fright Night"),
    ("tt0088763", "Back to the Future"),
    ("tt0093058", "Stand by Me"),
    ("tt0095953", "Rain Man"),
    ("tt0105236", "Reservoir Dogs"),
    ("tt0114814", "The Usual Suspects"),
    ("tt0119217", "Good Will Hunting"),
    ("tt0120338", "Titanic"),
    ("tt0120735", "The Lord of the Rings: The Fellowship of the Ring"),
    ("tt0137523", "Fight Club (fila)"),
    ("tt0169547", "American Beauty"),
    ("tt0209144", "The Fast and the Furious"),
    ("tt0295297", "Harry Potter and the Chamber of Secrets"),
    ("tt0304141", "Harry Potter and the Prisoner of Azkaban"),
    ("tt0330373", "Harry Potter and the Goblet of Fire"),
    ("tt0373889", "Harry Potter and the Order of the Phoenix"),
    ("tt0417741", "Harry Potter and the Half-Blood Prince"),
    ("tt0926084", "Harry Potter and the Deathly Hallows: Part 1"),
    ("tt1201607", "Harry Potter and the Deathly Hallows: Part 2"),
    ("tt0848228", "The Avengers"),
    ("tt2015381", "Guardians of the Galaxy"),
    ("tt3498820", "Captain America: Civil War"),
    ("tt4154756", "Avengers: Infinity War"),
    ("tt4154664", "Avengers: Endgame"),
    ("tt1825684", "Black Panther"),
    ("tt3501632", "Suzume"),
    ("tt10648342", "Thor: Love and Thunder"),
    ("tt9419884", "Doctor Strange in the Multiverse of Madness"),
    ("tt6320622", "Spider-Man: Far From Home"),
]

# Garantir IDs únicos na fila e sem colisão com assistidos
_assistidos_ids = {fid for fid, _ in ASSISTIDOS}
FILA_60 = [(fid, tit) for fid, tit in FILA_60 if fid not in _assistidos_ids]
# Remover duplicata Fight Club placeholder se sobrou
_seen: set[str] = set()
FILA_60_UNIQUE: list[tuple[str, str]] = []
for fid, tit in FILA_60:
    if fid in _seen:
        continue
    _seen.add(fid)
    FILA_60_UNIQUE.append((fid, tit))
FILA_60 = FILA_60_UNIQUE

EXTRA_FILA = [
    ("tt0112573", "Braveheart"),
    ("tt0103064", "Terminator 2: Judgment Day"),
    ("tt0082971", "Raiders of the Lost Ark"),
    ("tt0078748", "Alien"),
    ("tt0088247", "The Terminator"),
]
for fid, tit in EXTRA_FILA:
    if len(FILA_60) >= 60:
        break
    if fid not in _assistidos_ids and fid not in _seen:
        _seen.add(fid)
        FILA_60.append((fid, tit))

if len(FILA_60) < 60:
    raise SystemExit(f"Lista FILA_60 tem só {len(FILA_60)} filmes; ajuste EXTRA_FILA.")


def limpar_watchlist() -> int:
    n = 0
    for row in convex_db.list_by_status("watchlist"):
        fid = row.get("filme_id")
        if fid:
            convex_db.remove_by_filme_status(fid, "watchlist")
            n += 1
    return n


def seed_assistidos() -> tuple[int, int]:
    ok = 0
    skip = 0
    for filme_id, titulo in ASSISTIDOS:
        if convex_db.get_status_by_filme(filme_id) == "assistido":
            skip += 1
        else:
            convex_db.marcar_assistido(SEED_USER, filme_id, titulo)
            ok += 1
        convex_db.add_assistido(
            filme_id,
            SEED_USER,
            SEED_USER,
            SEED_DISPLAY,
            None,
            source="manual",
        )
    return ok, skip


def seed_fila() -> tuple[int, int]:
    ok = 0
    skip = 0
    for filme_id, titulo in FILA_60[:60]:
        st = convex_db.get_status_by_filme(filme_id)
        if st == "watchlist":
            skip += 1
            continue
        convex_db.adicionar_fila(SEED_USER, filme_id, titulo)
        ok += 1
    return ok, skip


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed assistidos + 60 na fila")
    parser.add_argument(
        "--limpar-fila",
        action="store_true",
        help="Remove todos os filmes da watchlist antes de inserir os 60 de teste",
    )
    args = parser.parse_args()

    if args.limpar_fila:
        removidos = limpar_watchlist()
        print(f"Watchlist limpa: {removidos} removido(s).")

    a_ok, a_skip = seed_assistidos()
    f_ok, f_skip = seed_fila()

    fila_total = len(convex_db.list_by_status("watchlist"))
    assist_total = len(convex_db.list_by_status("assistido"))

    print(f"Assistidos: +{a_ok} novo(s), {a_skip} já existente(s). Total: {assist_total}")
    print(f"Fila: +{f_ok} novo(s), {f_skip} já na fila. Total watchlist: {fila_total}")
    if fila_total < 60:
        print(f"Aviso: watchlist tem {fila_total} itens (meta 60). Rode com --limpar-fila ou remova conflitos.")


if __name__ == "__main__":
    main()
