from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Índice del archivo local de grabaciones (archiver.py): qué segmento de qué canal vive en qué
# archivo, tal como quedó tras aterrizar (una copia sin tocar de lo que entrega el DVR) o tras
# compactarlo (recomprimido por GPU/CPU, ver archive_compactor.py). Una sola tabla, SQLite con
# WAL: el archivador es el único que escribe, pero la app (Fase 3: leer del disco antes que del
# DVR) y este mismo módulo desde otro proceso deben poder LEER sin que una escritura los bloquee.
#
# El archivo por canal es siempre un tramo CONTINUO que solo crece hacia el pasado que aún no se
# ha archivado (se pide lo más viejo primero) y hacia el presente (según avanza el reloj), y solo
# se recorta por el extremo viejo (desalojo por presupuesto de disco, ver `oldest_segment`) --
# nunca se abren huecos a propósito, así que "el cursor" de un canal es simplemente el fin de su
# segmento más reciente.

SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    channel INTEGER NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    bytes INTEGER NOT NULL,
    compacted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_channel_start ON segments (channel, start);

-- Hasta dónde revisó el archivador cada canal (archiver.py): avanza aunque un tramo no tuviera
-- grabación (un hueco real no debe hacer que se pregunte lo mismo una y otra vez), así que NO es
-- lo mismo que "el fin del último segmento guardado" (`latest_end`, más abajo).
CREATE TABLE IF NOT EXISTS cursors (
    channel INTEGER PRIMARY KEY,
    checked_until TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Segment:
    id: int
    channel: int
    start: datetime
    end: datetime
    path: str  # relativo a la carpeta del archivo (ARCHIVE_DIR): así la carpeta entera es portable
    bytes: int
    compacted: bool

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _row_to_segment(row: sqlite3.Row) -> Segment:
    return Segment(
        id=row["id"],
        channel=row["channel"],
        start=_parse(row["start"]),
        end=_parse(row["end"]),
        path=row["path"],
        bytes=row["bytes"],
        compacted=bool(row["compacted"]),
    )


def open_db(path: Path) -> sqlite3.Connection:
    """Abre (o crea) el índice en `path`. WAL + busy_timeout generoso: varios procesos pueden
    tenerlo abierto a la vez (el archivador escribiendo, la app leyendo) sin que una escritura
    corta bloquee a un lector, y sin que un lector lento haga fallar a quien escribe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def add_segment(
    conn: sqlite3.Connection,
    channel: int,
    start: datetime,
    end: datetime,
    path: str,
    size_bytes: int,
    compacted: bool = False,
    now: datetime | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO segments (channel, start, end, path, bytes, compacted, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (channel, _iso(start), _iso(end), path, size_bytes, int(compacted), _iso(now or datetime.now())),
    )
    return int(cursor.lastrowid)


def mark_compacted(conn: sqlite3.Connection, segment_id: int, new_path: str, new_bytes: int) -> None:
    """El segmento crudo (.dav, tal cual del DVR) fue reemplazado por su versión comprimida:
    mismo rango de tiempo, otro archivo y otro tamaño."""
    conn.execute("UPDATE segments SET path = ?, bytes = ?, compacted = 1 WHERE id = ?", (new_path, new_bytes, segment_id))


def delete_segment(conn: sqlite3.Connection, segment_id: int) -> None:
    """Solo quita la fila del índice; borrar el archivo en disco es responsabilidad de quien
    llama (ver archiver.evict_oldest), para que este módulo no toque el sistema de archivos."""
    conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))


def get_segment(conn: sqlite3.Connection, segment_id: int) -> Segment | None:
    row = conn.execute("SELECT * FROM segments WHERE id = ?", (segment_id,)).fetchone()
    return _row_to_segment(row) if row else None


def segments_for_channel(conn: sqlite3.Connection, channel: int) -> list[Segment]:
    rows = conn.execute("SELECT * FROM segments WHERE channel = ? ORDER BY start", (channel,)).fetchall()
    return [_row_to_segment(row) for row in rows]


def segments_covering(conn: sqlite3.Connection, channel: int, start: datetime, end: datetime) -> list[Segment]:
    """Los segmentos de `channel` que se cruzan con [start, end), en orden. Para cuando la Fase 3
    (leer del disco antes que del DVR) necesite saber qué de un rango pedido ya está archivado."""
    rows = conn.execute(
        "SELECT * FROM segments WHERE channel = ? AND start < ? AND end > ? ORDER BY start",
        (channel, _iso(end), _iso(start)),
    ).fetchall()
    return [_row_to_segment(row) for row in rows]


def latest_end(conn: sqlite3.Connection, channel: int) -> datetime | None:
    """El fin del segmento más reciente de `channel`: de ahí en adelante sigue el archivador."""
    row = conn.execute("SELECT MAX(end) AS m FROM segments WHERE channel = ?", (channel,)).fetchone()
    return _parse(row["m"]) if row and row["m"] is not None else None


def oldest_start(conn: sqlite3.Connection, channel: int) -> datetime | None:
    row = conn.execute("SELECT MIN(start) AS m FROM segments WHERE channel = ?", (channel,)).fetchone()
    return _parse(row["m"]) if row and row["m"] is not None else None


def oldest_segment(conn: sqlite3.Connection) -> Segment | None:
    """El segmento más viejo de TODO el archivo (cualquier canal): el primero que se desaloja
    cuando el presupuesto de disco se llena."""
    row = conn.execute("SELECT * FROM segments ORDER BY start LIMIT 1").fetchone()
    return _row_to_segment(row) if row else None


def total_bytes(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(SUM(bytes), 0) AS s FROM segments").fetchone()
    return int(row["s"])


def channels(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT DISTINCT channel FROM segments ORDER BY channel").fetchall()
    return [row["channel"] for row in rows]


def get_cursor(conn: sqlite3.Connection, channel: int) -> datetime | None:
    row = conn.execute("SELECT checked_until FROM cursors WHERE channel = ?", (channel,)).fetchone()
    return _parse(row["checked_until"]) if row else None


def set_cursor(conn: sqlite3.Connection, channel: int, moment: datetime) -> None:
    conn.execute(
        "INSERT INTO cursors (channel, checked_until) VALUES (?, ?) "
        "ON CONFLICT(channel) DO UPDATE SET checked_until = excluded.checked_until",
        (channel, _iso(moment)),
    )


def pending_compaction(conn: sqlite3.Connection, limit: int = 50) -> list[Segment]:
    """Segmentos aterrizados (crudos) que aún no se compactaron, los más viejos primero: por ese
    orden los toma el compactador, así lo más viejo (lo que más urge liberar) se achica primero."""
    rows = conn.execute("SELECT * FROM segments WHERE compacted = 0 ORDER BY start LIMIT ?", (limit,)).fetchall()
    return [_row_to_segment(row) for row in rows]
