from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from framepilot.models import PhotoRecord


RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw"}


def discover_raw_files(folder: str | Path, cancelled: Callable[[], bool] | None = None) -> list[PhotoRecord]:
    root = Path(folder)
    if not root.is_dir():
        raise NotADirectoryError(root)
    photos: list[PhotoRecord] = []
    for path in root.rglob("*"):
        if cancelled and cancelled():
            break
        try:
            if path.is_file() and path.suffix.lower() in RAW_EXTENSIONS:
                stat = path.stat()
                photos.append(PhotoRecord(path=path.resolve(), size=stat.st_size, modified_ns=stat.st_mtime_ns))
        except OSError:
            continue
    photos.sort(key=lambda p: p.path.name.casefold())
    return photos

