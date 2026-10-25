from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Sequence

from framepilot.models import AnalysisResult, CullStatus, DevelopSettings, PhotoRecord


SCHEMA_VERSION = 1


class ProjectDatabase:
    """SQLite-backed project persistence with WAL and atomic transactions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self._create_schema()

    def _create_schema(self) -> None:
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS photos(
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    capture_time TEXT,
                    camera TEXT,
                    lens TEXT,
                    rating INTEGER NOT NULL DEFAULT 0 CHECK(rating BETWEEN 0 AND 5),
                    color_label TEXT NOT NULL DEFAULT '',
                    cull_status TEXT NOT NULL DEFAULT 'unrated',
                    cull_override INTEGER NOT NULL DEFAULT 0,
                    settings_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL DEFAULT '{}',
                    export_status TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_photos_capture ON photos(capture_time);
                CREATE INDEX IF NOT EXISTS idx_photos_cull ON photos(cull_status);
            """)
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version',?)",
                       (str(SCHEMA_VERSION),))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def upsert_photo(self, photo: PhotoRecord) -> int:
        with self.transaction() as db:
            db.execute("""
                INSERT INTO photos(path,size,modified_ns,capture_time,camera,lens,rating,color_label,
                    cull_status,cull_override,settings_json,analysis_json,export_status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    size=excluded.size, modified_ns=excluded.modified_ns,
                    capture_time=COALESCE(excluded.capture_time,photos.capture_time),
                    camera=COALESCE(excluded.camera,photos.camera), lens=COALESCE(excluded.lens,photos.lens),
                    updated_at=CURRENT_TIMESTAMP
            """, self._params(photo))
            row = db.execute("SELECT id FROM photos WHERE path=?", (str(photo.path.resolve()),)).fetchone()
        photo.id = int(row[0])
        return photo.id

    def save_photo(self, photo: PhotoRecord) -> None:
        if photo.id is None:
            self.upsert_photo(photo)
            return
        with self.transaction() as db:
            db.execute("""UPDATE photos SET rating=?,color_label=?,cull_status=?,cull_override=?,
                settings_json=?,analysis_json=?,export_status=?,capture_time=?,camera=?,lens=?,
                updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (photo.rating, photo.color_label, photo.cull_status.value, int(photo.cull_override),
                 photo.settings.to_json(), json.dumps(asdict(photo.analysis)), photo.export_status,
                 photo.capture_time, photo.camera, photo.lens, photo.id))

    def save_many(self, photos: Sequence[PhotoRecord]) -> None:
        with self.transaction() as db:
            for photo in photos:
                if photo.id is None:
                    db.execute("""INSERT OR IGNORE INTO photos(path,size,modified_ns,settings_json,analysis_json)
                        VALUES(?,?,?,?,?)""", (str(photo.path.resolve()), photo.size, photo.modified_ns,
                        photo.settings.to_json(), json.dumps(asdict(photo.analysis))))
                    photo.id = db.execute("SELECT id FROM photos WHERE path=?",
                                          (str(photo.path.resolve()),)).fetchone()[0]
                db.execute("""UPDATE photos SET rating=?,color_label=?,cull_status=?,cull_override=?,
                    settings_json=?,analysis_json=?,export_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (photo.rating, photo.color_label, photo.cull_status.value, int(photo.cull_override),
                     photo.settings.to_json(), json.dumps(asdict(photo.analysis)), photo.export_status, photo.id))

    def load_photos(self) -> list[PhotoRecord]:
        return [self._from_row(row) for row in self.connection.execute(
            "SELECT * FROM photos ORDER BY COALESCE(capture_time,''), path")]

    def set_metadata(self, key: str, value: str) -> None:
        with self.transaction() as db:
            db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", (key, value))

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _params(p: PhotoRecord) -> tuple:
        return (str(p.path.resolve()), p.size, p.modified_ns, p.capture_time, p.camera, p.lens,
                p.rating, p.color_label, p.cull_status.value, int(p.cull_override),
                p.settings.to_json(), json.dumps(asdict(p.analysis)), p.export_status)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PhotoRecord:
        analysis_payload = json.loads(row["analysis_json"] or "{}")
        allowed = AnalysisResult.__dataclass_fields__.keys()
        analysis = AnalysisResult(**{k: v for k, v in analysis_payload.items() if k in allowed})
        return PhotoRecord(id=row["id"], path=Path(row["path"]), size=row["size"],
            modified_ns=row["modified_ns"], capture_time=row["capture_time"], camera=row["camera"],
            lens=row["lens"], rating=row["rating"], color_label=row["color_label"],
            cull_status=CullStatus(row["cull_status"]), cull_override=bool(row["cull_override"]),
            settings=DevelopSettings.from_json(row["settings_json"]), analysis=analysis,
            export_status=row["export_status"])
