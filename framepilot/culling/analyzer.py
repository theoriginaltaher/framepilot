from __future__ import annotations

from collections import defaultdict
import hashlib
import math
from pathlib import Path
from typing import Iterable

from framepilot.models import AnalysisResult, CullStatus, PhotoRecord


def _deps():
    import numpy as np
    from PIL import Image
    return np, Image


def perceptual_dhash(image, size: int = 8) -> str:
    np, Image = _deps()
    gray = image.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    values = np.asarray(gray, dtype=np.uint8)
    bits = values[:, 1:] > values[:, :-1]
    number = sum(int(bit) << index for index, bit in enumerate(bits.flatten()))
    return f"{number:0{size * size // 4}x}"


def hash_distance(left: str, right: str) -> int:
    if not left or not right or len(left) != len(right):
        return 10_000
    return (int(left, 16) ^ int(right, 16)).bit_count()


def analyse_image(image) -> AnalysisResult:
    """Deterministic technical analysis; no ML model is claimed or required."""
    np, Image = _deps()
    rgb = np.asarray(image.convert("RGB").resize((1024, 1024), Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
    gray = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    lap = (-4 * gray + np.roll(gray, 1, 0) + np.roll(gray, -1, 0)
           + np.roll(gray, 1, 1) + np.roll(gray, -1, 1))
    sharpness_raw = float(np.var(lap) * 10_000)
    sharpness = max(0.0, min(100.0, 100 * (1 - math.exp(-sharpness_raw / 55))))
    mean = float(gray.mean())
    exposure_score = max(0.0, 100.0 - abs(mean - 0.46) * 220)
    black_clip = float((gray < 0.005).mean())
    white_clip = float((gray > 0.995).mean())
    clipping = black_clip + white_clip
    exposure_score *= max(0.0, 1.0 - min(1.0, clipping * 4))
    p05, p95 = np.percentile(gray, [5, 95])
    contrast_score = max(0.0, min(100.0, float((p95 - p05) * 140)))
    quality = 0.52 * sharpness + 0.33 * exposure_score + 0.15 * contrast_score
    reasons = [f"sharpness {sharpness:.0f}/100", f"exposure {exposure_score:.0f}/100"]
    if clipping > 0.03:
        reasons.append(f"{clipping:.1%} clipped pixels")
    return AnalysisResult(sharpness=sharpness, exposure_score=exposure_score,
        contrast_score=contrast_score, clipping_fraction=clipping, quality_score=quality,
        perceptual_hash=perceptual_dhash(image), explanation=", ".join(reasons))


def suggested_status(result: AnalysisResult) -> CullStatus:
    if result.preview_failed or result.quality_score < 32 or result.sharpness < 18:
        return CullStatus.REJECT
    if result.quality_score >= 67 and result.sharpness >= 45:
        return CullStatus.KEEP
    return CullStatus.REVIEW


def group_similar(photos: Iterable[PhotoRecord], max_distance: int = 8,
                  window: int = 12) -> list[list[PhotoRecord]]:
    """Near-linear local-window grouping suitable for capture-ordered event sets.

    It avoids all-pairs comparison: each frame is compared only with a bounded
    neighborhood. This fits burst/event workflows; non-adjacent duplicates may be missed.
    """
    ordered = list(photos)
    parent = list(range(len(ordered)))
    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    for i, photo in enumerate(ordered):
        if not photo.analysis.perceptual_hash:
            continue
        for j in range(max(0, i - window), i):
            other = ordered[j]
            if hash_distance(photo.analysis.perceptual_hash, other.analysis.perceptual_hash) <= max_distance:
                union(i, j)
    groups: dict[int, list[PhotoRecord]] = defaultdict(list)
    for i, photo in enumerate(ordered):
        groups[find(i)].append(photo)
    output = [items for items in groups.values() if len(items) > 1]
    for items in output:
        gid = "burst-" + hashlib.sha1("|".join(p.identity for p in items).encode()).hexdigest()[:10]
        best = max(items, key=lambda p: p.analysis.quality_score)
        for p in items:
            p.analysis.group_id = gid
            if not p.cull_override:
                p.cull_status = CullStatus.KEEP if p is best else CullStatus.REVIEW
                p.analysis.explanation += "; best in burst" if p is best else "; similar frame available"
    return output
