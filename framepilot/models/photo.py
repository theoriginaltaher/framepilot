from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .settings import DevelopSettings


class CullStatus(StrEnum):
    UNRATED = "unrated"
    KEEP = "keep"
    REVIEW = "review"
    REJECT = "reject"


@dataclass(slots=True)
class AnalysisResult:
    sharpness: float = 0.0
    exposure_score: float = 0.0
    contrast_score: float = 0.0
    clipping_fraction: float = 0.0
    quality_score: float = 0.0
    perceptual_hash: str = ""
    group_id: str | None = None
    explanation: str = "Not analysed"
    preview_failed: bool = False


@dataclass(slots=True)
class PhotoRecord:
    path: Path
    size: int
    modified_ns: int
    id: int | None = None
    capture_time: str | None = None
    camera: str | None = None
    lens: str | None = None
    rating: int = 0
    color_label: str = ""
    cull_status: CullStatus = CullStatus.UNRATED
    cull_override: bool = False
    settings: DevelopSettings = field(default_factory=DevelopSettings)
    analysis: AnalysisResult = field(default_factory=AnalysisResult)
    export_status: str = ""

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def identity(self) -> str:
        return f"{self.path.resolve()}|{self.size}|{self.modified_ns}"

    def display_metadata(self) -> dict[str, Any]:
        return {"filename": self.filename, "capture_time": self.capture_time or "",
                "camera": self.camera or "", "rating": self.rating,
                "status": self.cull_status.value}

