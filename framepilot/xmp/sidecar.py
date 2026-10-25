from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from framepilot.models import DevelopSettings

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "crs": "http://ns.adobe.com/camera-raw-settings/1.0/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
}
for prefix, uri in NS.items():
    ET.register_namespace(prefix, uri)

# Process Version 6 was introduced with ACR 15.4. This conservative baseline uses
# the established 2012 controls and avoids newer masks/profile payloads.
CAMERA_RAW_VERSION = "15.4"
PROCESS_VERSION = "15.4"


@dataclass(slots=True)
class XMPExportResult:
    source: Path
    sidecar: Path
    success: bool
    backup: Path | None = None
    message: str = ""


@dataclass(slots=True)
class XMPValidation:
    valid: bool
    errors: list[str]
    settings: DevelopSettings | None = None


def sidecar_path(raw_path: str | Path) -> Path:
    """Adobe-compatible same-basename, same-directory XMP path.

    FramePilot intentionally exports a sidecar for DNG too, rather than mutating
    the original DNG, although Adobe commonly embeds XMP in DNG files.
    """
    return Path(raw_path).with_suffix(".xmp")


def _fmt_number(value: float | int, signed: bool = True) -> str:
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    if signed and value > 0:
        return "+" + text
    return text


def _develop_attributes(s: DevelopSettings, raw_name: str) -> dict[str, str]:
    s = s.validated()
    crs = lambda key: f"{{{NS['crs']}}}{key}"
    attrs = {
        crs("Version"): CAMERA_RAW_VERSION,
        crs("ProcessVersion"): PROCESS_VERSION,
        crs("HasSettings"): "True",
        crs("RawFileName"): raw_name,
        crs("WhiteBalance"): s.white_balance,
        crs("Exposure2012"): _fmt_number(s.exposure),
        crs("Contrast2012"): _fmt_number(s.contrast),
        crs("Highlights2012"): _fmt_number(s.highlights),
        crs("Shadows2012"): _fmt_number(s.shadows),
        crs("Whites2012"): _fmt_number(s.whites),
        crs("Blacks2012"): _fmt_number(s.blacks),
        crs("Texture"): _fmt_number(s.texture),
        crs("Clarity2012"): _fmt_number(s.clarity),
        crs("Dehaze"): _fmt_number(s.dehaze),
        crs("Vibrance"): _fmt_number(s.vibrance),
        crs("Saturation"): _fmt_number(s.saturation),
        crs("Sharpness"): str(s.sharpening),
        crs("LuminanceSmoothing"): str(s.luminance_noise_reduction),
        crs("ColorNoiseReduction"): str(s.color_noise_reduction),
    }
    if s.white_balance == "Custom":
        attrs[crs("Temperature")] = str(s.temperature)
        attrs[crs("Tint")] = _fmt_number(s.tint)
    return attrs


def build_tree(raw_path: str | Path, settings: DevelopSettings, existing: Path | None = None) -> ET.ElementTree:
    raw = Path(raw_path)
    tree: ET.ElementTree
    description: ET.Element
    if existing and existing.exists():
        tree = ET.parse(existing)
        root = tree.getroot()
        description = root.find(f".//{{{NS['rdf']}}}Description")  # type: ignore[assignment]
        if description is None:
            rdf = root.find(f".//{{{NS['rdf']}}}RDF")
            if rdf is None:
                rdf = ET.SubElement(root, f"{{{NS['rdf']}}}RDF")
            description = ET.SubElement(rdf, f"{{{NS['rdf']}}}Description",
                                        {f"{{{NS['rdf']}}}about": ""})
    else:
        root = ET.Element(f"{{{NS['x']}}}xmpmeta", {f"{{{NS['x']}}}xmptk": "FramePilot 0.1"})
        rdf = ET.SubElement(root, f"{{{NS['rdf']}}}RDF")
        description = ET.SubElement(rdf, f"{{{NS['rdf']}}}Description",
                                    {f"{{{NS['rdf']}}}about": ""})
        tree = ET.ElementTree(root)
    description.attrib.update(_develop_attributes(settings, raw.name))
    description.set(f"{{{NS['xmp']}}}MetadataDate", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    ET.indent(tree, space="  ")
    return tree


def export_sidecar(raw_path: str | Path, settings: DevelopSettings, *, overwrite: bool = False,
                   backup: bool = True) -> XMPExportResult:
    raw = Path(raw_path)
    output = sidecar_path(raw)
    if output.exists() and not overwrite:
        return XMPExportResult(raw, output, False, message="Sidecar exists; overwrite was not authorised")
    backup_path: Path | None = None
    try:
        tree = build_tree(raw, settings, output if output.exists() else None)
        validation = validate_tree(tree)
        if not validation.valid:
            return XMPExportResult(raw, output, False, message="; ".join(validation.errors))
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and backup:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = output.with_name(output.name + f".bak-{stamp}")
            shutil.copy2(output, backup_path)
        fd, temporary_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write('<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'.encode("utf-8"))
                tree.write(handle, encoding="utf-8", xml_declaration=False)
                handle.write(b'\n<?xpacket end="w"?>\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, output)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return XMPExportResult(raw, output, True, backup_path, "XMP exported atomically")
    except Exception as exc:
        return XMPExportResult(raw, output, False, backup_path, str(exc))


def parse_sidecar(path: str | Path) -> DevelopSettings:
    tree = ET.parse(path)
    description = tree.getroot().find(f".//{{{NS['rdf']}}}Description")
    if description is None:
        raise ValueError("XMP has no rdf:Description")
    get = lambda key, default="0": description.get(f"{{{NS['crs']}}}{key}", default)
    wb = get("WhiteBalance", "As Shot")
    return DevelopSettings(
        exposure=float(get("Exposure2012")), temperature=int(get("Temperature", "5500")),
        tint=int(get("Tint")), contrast=int(get("Contrast2012")),
        highlights=int(get("Highlights2012")), shadows=int(get("Shadows2012")),
        whites=int(get("Whites2012")), blacks=int(get("Blacks2012")),
        texture=int(get("Texture")), clarity=int(get("Clarity2012")), dehaze=int(get("Dehaze")),
        vibrance=int(get("Vibrance")), saturation=int(get("Saturation")),
        sharpening=int(get("Sharpness", "40")),
        luminance_noise_reduction=int(get("LuminanceSmoothing")),
        color_noise_reduction=int(get("ColorNoiseReduction", "25")), white_balance=wb,
    ).validated()


def validate_tree(tree: ET.ElementTree) -> XMPValidation:
    errors: list[str] = []
    description = tree.getroot().find(f".//{{{NS['rdf']}}}Description")
    if description is None:
        return XMPValidation(False, ["Missing rdf:Description"])
    for field in ("Version", "ProcessVersion", "HasSettings", "Exposure2012", "WhiteBalance"):
        if f"{{{NS['crs']}}}{field}" not in description.attrib:
            errors.append(f"Missing crs:{field}")
    settings = None
    if not errors:
        try:
            # Avoid round-tripping through a file: validate attribute types/ranges directly.
            get = lambda key, default="0": description.get(f"{{{NS['crs']}}}{key}", default)
            settings = DevelopSettings(exposure=float(get("Exposure2012")),
                contrast=int(get("Contrast2012")), highlights=int(get("Highlights2012")),
                shadows=int(get("Shadows2012")), whites=int(get("Whites2012")),
                blacks=int(get("Blacks2012")), texture=int(get("Texture")),
                clarity=int(get("Clarity2012")), dehaze=int(get("Dehaze")),
                vibrance=int(get("Vibrance")), saturation=int(get("Saturation")),
                sharpening=int(get("Sharpness", "40")),
                luminance_noise_reduction=int(get("LuminanceSmoothing")),
                color_noise_reduction=int(get("ColorNoiseReduction", "25")),
                white_balance=get("WhiteBalance", "As Shot"),
                temperature=int(get("Temperature", "5500")), tint=int(get("Tint"))).validated()
        except (ValueError, TypeError) as exc:
            errors.append(f"Invalid Camera Raw value: {exc}")
    return XMPValidation(not errors, errors, settings)


def validate_sidecar(path: str | Path) -> XMPValidation:
    try:
        return validate_tree(ET.parse(path))
    except (ET.ParseError, OSError) as exc:
        return XMPValidation(False, [str(exc)])

