import xml.etree.ElementTree as ET

from framepilot.models import DevelopSettings
from framepilot.xmp import export_sidecar, parse_sidecar, sidecar_path, validate_sidecar
from framepilot.xmp.sidecar import NS


def test_xmp_export_is_valid_and_round_trips(tmp_path):
    raw = tmp_path / "IMG_0042.CR3"; raw.write_bytes(b"fixture placeholder")
    settings = DevelopSettings(exposure=1.15, contrast=12, highlights=-44, shadows=31,
        whites=8, blacks=-9, texture=6, clarity=11, dehaze=3, vibrance=14,
        saturation=-2, white_balance="Custom", temperature=4850, tint=9,
        sharpening=55, luminance_noise_reduction=18, color_noise_reduction=28)
    result = export_sidecar(raw, settings)
    assert result.success, result.message
    assert result.sidecar == tmp_path / "IMG_0042.xmp"
    validation = validate_sidecar(result.sidecar)
    assert validation.valid, validation.errors
    restored = parse_sidecar(result.sidecar)
    assert restored == settings

    description = ET.parse(result.sidecar).getroot().find(f".//{{{NS['rdf']}}}Description")
    assert description.get(f"{{{NS['crs']}}}Exposure2012") == "+1.15"
    assert description.get(f"{{{NS['crs']}}}Highlights2012") == "-44"
    assert description.get(f"{{{NS['crs']}}}ProcessVersion") == "15.4"


def test_existing_metadata_is_preserved_and_backup_created(tmp_path):
    raw = tmp_path / "NIK_1001.NEF"; raw.write_bytes(b"raw")
    xmp = sidecar_path(raw)
    xmp.write_text('<?xml version="1.0"?><x:xmpmeta xmlns:x="adobe:ns:meta/" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><rdf:RDF>'
        '<rdf:Description rdf:about="" dc:format="image/x-nikon-nef" />'
        '</rdf:RDF></x:xmpmeta>', encoding="utf-8")
    refused = export_sidecar(raw, DevelopSettings())
    assert not refused.success
    result = export_sidecar(raw, DevelopSettings(exposure=-0.5), overwrite=True)
    assert result.success and result.backup and result.backup.exists()
    description = ET.parse(xmp).getroot().find(f".//{{{NS['rdf']}}}Description")
    assert description.get("{http://purl.org/dc/elements/1.1/}format") == "image/x-nikon-nef"


def test_dng_uses_external_sidecar_without_modifying_original(tmp_path):
    raw = tmp_path / "shot.DNG"; payload = b"immutable dng"; raw.write_bytes(payload)
    result = export_sidecar(raw, DevelopSettings(exposure=0.2))
    assert result.success and result.sidecar.name == "shot.xmp"
    assert raw.read_bytes() == payload

