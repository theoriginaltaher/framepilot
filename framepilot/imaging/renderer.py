from __future__ import annotations

from framepilot.models import DevelopSettings


def render_preview(image, settings: DevelopSettings):
    """Approximate, colour-managed-display preview pipeline.

    This is deliberately separate from XMP export and is not claimed to match ACR.
    Every enabled control changes rendered pixels using bounded transforms.
    """
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter

    s = settings.validated()
    arr = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0

    # White balance approximation via reciprocal warm/cool gains and green-magenta tint.
    if s.white_balance == "Custom":
        kelvin_shift = np.clip(np.log2(s.temperature / 5500.0), -2.0, 2.0)
        tint = s.tint / 150.0
        gains = np.array([2 ** (0.16 * kelvin_shift + 0.07 * tint),
                          2 ** (-0.10 * tint),
                          2 ** (-0.16 * kelvin_shift + 0.07 * tint)], dtype=np.float32)
        arr *= gains
    arr *= 2.0 ** s.exposure

    # Tonal masks approximate ACR's local tone controls while remaining monotonic.
    lum = arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    shadow_mask = np.clip(1.0 - lum * 2.0, 0.0, 1.0)[..., None]
    highlight_mask = np.clip((lum - 0.5) * 2.0, 0.0, 1.0)[..., None]
    arr += shadow_mask * (s.shadows / 100.0) * 0.28
    arr += highlight_mask * (s.highlights / 100.0) * 0.28
    arr += (1.0 - lum[..., None]) ** 4 * (s.blacks / 100.0) * 0.16
    arr += lum[..., None] ** 4 * (s.whites / 100.0) * 0.16
    arr = (arr - 0.5) * (1.0 + s.contrast / 120.0) + 0.5
    arr = np.clip(arr, 0.0, 1.0)

    # Saturation plus luminance-protected vibrance.
    lum3 = (arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[..., None]
    chroma = arr.max(axis=2, keepdims=True) - arr.min(axis=2, keepdims=True)
    sat_factor = 1.0 + s.saturation / 100.0 + (s.vibrance / 100.0) * (1.0 - chroma)
    arr = lum3 + (arr - lum3) * sat_factor
    arr = np.clip(arr, 0.0, 1.0)

    output = Image.fromarray((arr * 255 + 0.5).astype(np.uint8), "RGB")
    if s.dehaze:
        output = ImageEnhance.Contrast(output).enhance(1.0 + s.dehaze / 180.0)
    if s.clarity or s.texture:
        radius = 3 if s.texture else 8
        amount = (s.clarity * 0.012) + (s.texture * 0.008)
        output = output.filter(ImageFilter.UnsharpMask(radius=radius, percent=max(0, int(100 * amount)), threshold=2)) if amount > 0 else output.filter(ImageFilter.GaussianBlur(abs(amount) * 0.8))
    if s.luminance_noise_reduction:
        output = output.filter(ImageFilter.GaussianBlur(s.luminance_noise_reduction / 80.0))
    if s.sharpening:
        output = output.filter(ImageFilter.UnsharpMask(radius=1.2, percent=s.sharpening, threshold=3))
    return output


def export_jpeg(image, settings: DevelopSettings, destination, quality: int = 92) -> None:
    rendered = render_preview(image, settings)
    rendered.save(destination, "JPEG", quality=max(60, min(100, quality)), optimize=True,
                  progressive=True, icc_profile=image.info.get("icc_profile"))
