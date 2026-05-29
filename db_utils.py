import json
import os
import sqlite3
from datetime import datetime, timezone

TABLES = (
    "listas",
    "eventos",
    "evento_participantes",
    "usuarios_assistidos",
)


def get_db_path() -> str:
    if os.path.exists("/data") or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return "/data/filmes.db"
    return "filmes.db"


def _ensure_eventos_columns(cursor: sqlite3.Cursor) -> None:
    cursor.execute("PRAGMA table_info(eventos)")
    cols = {row[1] for row in cursor.fetchall()}
    if "canal_temporario" not in cols:
        cursor.execute(
            "ALTER TABLE eventos ADD COLUMN canal_temporario INTEGER DEFAULT 0"
        )


def init_db() -> None:
    path = get_db_path()
    dirname = os.path.dirname(path)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname, exist_ok=True)

    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS listas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, filme_id TEXT, titulo TEXT, status TEXT
        );
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_event_id TEXT UNIQUE,
            filme_id TEXT NOT NULL,
            titulo TEXT NOT NULL,
            data_evento TEXT NOT NULL,
            canal_id TEXT,
            guild_id TEXT,
            status TEXT DEFAULT 'agendado',
            canal_temporario INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS evento_participantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            interessado INTEGER DEFAULT 0,
            entrou_canal INTEGER DEFAULT 0,
            UNIQUE(evento_id, user_id),
            FOREIGN KEY (evento_id) REFERENCES eventos(id)
        );
        CREATE TABLE IF NOT EXISTS usuarios_assistidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filme_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT,
            display_name TEXT,
            avatar TEXT,
            source TEXT DEFAULT 'manual',
            data_assistido TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(filme_id, user_id)
        );
        """
    )
    _ensure_eventos_columns(cursor)
    conn.commit()
    conn.close()


def export_database() -> dict:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": {},
    }
    for table in TABLES:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        payload["tables"][table] = [dict(row) for row in rows]
    conn.close()
    return payload


def import_database(payload: dict, *, replace: bool = True) -> dict:
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("Formato de backup inválido.")

    tables = payload.get("tables", {})
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()

    if replace:
        for table in reversed(TABLES):
            cursor.execute(f"DELETE FROM {table}")

    counts: dict[str, int] = {}
    for table in TABLES:
        rows = tables.get(table, [])
        if not isinstance(rows, list):
            continue
        inserted = 0
        for row in rows:
            if not isinstance(row, dict) or not row:
                continue
            cols = list(row.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_names = ", ".join(cols)
            try:
                cursor.execute(
                    f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})",
                    [row[c] for c in cols],
                )
                inserted += 1
            except sqlite3.Error:
                continue
        counts[table] = inserted

    conn.commit()
    conn.close()
    return counts
