from __future__ import annotations

import hashlib
import io
import logging
import os
from pathlib import Path
from typing import Any

from framepilot.models import PhotoRecord

log = logging.getLogger(__name__)


def default_cache_dir() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return root / "FramePilot" / "cache" / "thumbnails-v1"


class PreviewDecoder:
    def __init__(self, cache_dir: str | Path | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_path(self, photo: PhotoRecord, size: int = 480) -> Path:
        key = hashlib.sha256(f"{photo.identity}|{size}".encode("utf-8")).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.jpg"

    def thumbnail(self, photo: PhotoRecord, size: int = 480):
        from PIL import Image, ImageOps
        cached = self.cache_path(photo, size)
        if cached.exists():
            try:
                with Image.open(cached) as image:
                    return image.convert("RGB").copy()
            except OSError:
                cached.unlink(missing_ok=True)
        image = self.decode(photo.path, half_size=True)
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        cached.parent.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_suffix(".tmp")
        image.save(temporary, "JPEG", quality=86, optimize=True)
        os.replace(temporary, cached)
        return image

    def preview(self, photo: PhotoRecord, max_size: int = 2048):
        from PIL import Image
        image = self.decode(photo.path, half_size=False).convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return image

    def decode(self, path: str | Path, half_size: bool = True):
        from PIL import Image
        try:
            import rawpy
        except ImportError as exc:
            raise RuntimeError("RAW decoding requires rawpy. Install FramePilot dependencies first.") from exc
        with rawpy.imread(str(path)) as raw:
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    with Image.open(io.BytesIO(thumb.data)) as image:
                        return image.convert("RGB").copy()
                if thumb.format == rawpy.ThumbFormat.BITMAP:
                    return Image.fromarray(thumb.data).convert("RGB")
            except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
                pass
            rgb = raw.postprocess(use_camera_wb=True, half_size=half_size,
                                  no_auto_bright=True, output_bps=8)
            return Image.fromarray(rgb, "RGB")

    def populate_metadata(self, photo: PhotoRecord) -> None:
        """Best-effort metadata. ExifTool can be added later without shell interpolation."""
        try:
            from PIL import Image
            with Image.open(self.cache_path(photo)) as image:
                exif = image.getexif()
                photo.camera = str(exif.get(272) or "") or None
                captured = exif.get(36867) or exif.get(306)
                photo.capture_time = str(captured) if captured else photo.capture_time
        except Exception:
            log.debug("Metadata unavailable for %s", photo.path.name, exc_info=True)

    def clear_cache(self) -> tuple[int, int]:
        files = list(self.cache_dir.rglob("*.jpg")) if self.cache_dir.exists() else []
        bytes_removed = sum(p.stat().st_size for p in files if p.exists())
        for path in files:
            path.unlink(missing_ok=True)
        for directory in sorted((p for p in self.cache_dir.rglob("*") if p.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        return len(files), bytes_removed

