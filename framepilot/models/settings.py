from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import json
from typing import Any, ClassVar


@dataclass(slots=True)
class DevelopSettings:
    """Serializable, engine-neutral non-destructive develop settings.

    Ranges intentionally match Adobe Camera Raw's common UI domains where useful.
    Temperature is only emitted to XMP when white_balance is Custom.
    """

    exposure: float = 0.0
    temperature: int = 5500
    tint: int = 0
    contrast: int = 0
    highlights: int = 0
    shadows: int = 0
    whites: int = 0
    blacks: int = 0
    texture: int = 0
    clarity: int = 0
    dehaze: int = 0
    vibrance: int = 0
    saturation: int = 0
    sharpening: int = 40
    luminance_noise_reduction: int = 0
    color_noise_reduction: int = 25
    white_balance: str = "As Shot"

    RANGES: ClassVar[dict[str, tuple[float, float]]] = {
        "exposure": (-5.0, 5.0), "temperature": (2000, 50000), "tint": (-150, 150),
        "contrast": (-100, 100), "highlights": (-100, 100), "shadows": (-100, 100),
        "whites": (-100, 100), "blacks": (-100, 100), "texture": (-100, 100),
        "clarity": (-100, 100), "dehaze": (-100, 100), "vibrance": (-100, 100),
        "saturation": (-100, 100), "sharpening": (0, 150),
        "luminance_noise_reduction": (0, 100), "color_noise_reduction": (0, 100),
    }

    def validated(self) -> "DevelopSettings":
        values = asdict(self)
        for name, (low, high) in self.RANGES.items():
            value = values[name]
            values[name] = max(low, min(high, value))
        for field in fields(self):
            if field.type in ("int", int):
                values[field.name] = int(values[field.name])
        if values["white_balance"] not in {"As Shot", "Auto", "Custom"}:
            values["white_balance"] = "As Shot"
        return type(self)(**values)

    def with_value(self, name: str, value: Any) -> "DevelopSettings":
        if name not in {f.name for f in fields(self)}:
            raise KeyError(name)
        return replace(self, **{name: value}).validated()

    def to_json(self) -> str:
        return json.dumps(asdict(self.validated()), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str | None) -> "DevelopSettings":
        if not value:
            return cls()
        payload = json.loads(value)
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in allowed}).validated()


DEFAULT_SETTINGS = DevelopSettings()

