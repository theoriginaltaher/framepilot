from __future__ import annotations

from dataclasses import replace

from framepilot.models import DevelopSettings


PRESETS = {
    "Neutral Event": DevelopSettings(contrast=5, highlights=-15, shadows=12, vibrance=8),
    "Clean Portrait": DevelopSettings(exposure=0.15, highlights=-20, shadows=18, texture=-5,
                                      clarity=-3, vibrance=6, sharpening=30),
    "Stage Recovery": DevelopSettings(highlights=-45, shadows=25, blacks=-8, dehaze=4,
                                      vibrance=10, color_noise_reduction=35),
    "Punchy Natural": DevelopSettings(contrast=12, highlights=-22, shadows=10, whites=8,
                                      blacks=-10, texture=5, clarity=6, vibrance=14),
}


def preset_names() -> list[str]:
    return list(PRESETS)


def get_preset(name: str) -> DevelopSettings:
    return replace(PRESETS[name])

