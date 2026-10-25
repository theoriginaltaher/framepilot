from pathlib import Path

import numpy as np
from PIL import Image

from framepilot.culling.analyzer import analyse_image, hash_distance
from framepilot.culling import group_similar
from framepilot.models import AnalysisResult, CullStatus, PhotoRecord


def checkerboard(size=256):
    y, x = np.indices((size, size))
    pixels = (((x // 8 + y // 8) % 2) * 220 + 18).astype(np.uint8)
    return Image.fromarray(np.stack([pixels] * 3, axis=-1))


def test_sharp_image_scores_above_blurred_image():
    from PIL import ImageFilter
    sharp = checkerboard()
    blurred = sharp.filter(ImageFilter.GaussianBlur(8))
    assert analyse_image(sharp).sharpness > analyse_image(blurred).sharpness


def test_dhash_is_stable_for_same_image():
    first = analyse_image(checkerboard()).perceptual_hash
    second = analyse_image(checkerboard()).perceptual_hash
    assert hash_distance(first, second) == 0


def test_similarity_group_selects_strongest_candidate(tmp_path):
    photos = []
    for i, score in enumerate((42.0, 88.0, 60.0)):
        path = tmp_path / f"{i}.CR3"; path.write_bytes(b"x")
        photos.append(PhotoRecord(path, 1, i, analysis=AnalysisResult(
            quality_score=score, perceptual_hash="0f0f0f0f0f0f0f0f")))
    groups = group_similar(photos)
    assert len(groups) == 1
    assert photos[1].cull_status is CullStatus.KEEP
    assert photos[0].cull_status is CullStatus.REVIEW

