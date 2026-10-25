# FramePilot

FramePilot is a local-first Windows desktop application for browsing, culling, grading, and exporting non-destructive Adobe Camera Raw XMP sidecars for event-photo RAW files.

This repository contains a working MVP. It never uploads photographs, never deletes source files, and never writes into a RAW/DNG file. The visual preview is FramePilot's approximate renderer; exported XMP settings are interpreted independently by Adobe Camera Raw or Lightroom Classic and may render differently.

## What works

- Recursive import of CR2, CR3, NEF, ARW, DNG, RAF, ORF, RW2, PEF, and SRW files (actual decode coverage depends on the LibRaw version bundled by `rawpy`).
- Embedded-thumbnail-first browsing with an identity-keyed cache under `%LOCALAPPDATA%\FramePilot\cache`.
- Multi-selection, 0–5 ratings, and Keep/Review/Reject overrides. Shortcuts: `0`–`5`, `P`, `U`, and `X`.
- SQLite project files with WAL transactions, persisted settings, ratings, culling analysis, and export status.
- A real approximate preview renderer for exposure, custom white balance, tint, tonal controls, texture/clarity/dehaze, vibrance/saturation, sharpening, and luminance noise reduction.
- Copy, paste, reset, sync-selected, per-photo undo/redo, and four neutral event presets.
- Local deterministic technical analysis for sharpness, exposure/clipping, contrast, preview failure, perceptual similarity, burst grouping, and explainable suggestions.
- Cancellable background discovery, thumbnails, preview decode, analysis, XMP export, and JPEG export.
- Atomic same-basename XMP export, existing-RDF preservation where practical, explicit overwrite confirmation, timestamped backup, parser, and validator.
- Full-resolution JPEG export through the approximate rendering pipeline.

## Windows development setup

Use 64-bit Python 3.11 or 3.12. Python 3.12.10 is the last Python 3.12 release with a traditional Windows installer.

```powershell
cd "D:\GD - TH\00 - Development\FramePilot"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m framepilot
```

Exact run command after setup:

```powershell
.\.venv\Scripts\python.exe -m framepilot
```

If Windows resolves `python`/`py` only to a broken Microsoft Store alias, install a current 64-bit CPython from python.org or repair the Python Install Manager first. FramePilot does not require ExifTool for the MVP.

## Basic workflow

1. Create a `.fp-project` or open an existing one.
2. Open a card/folder containing RAW files. Import is recursive; originals remain untouched.
3. Browse thumbnails and run **Analyse**. Suggestions are heuristic, not model predictions, and are always overridable.
4. Select a reference frame, apply or tune a preset, then use **Sync selected**.
5. Select photos and choose **Export XMP**. Existing sidecars require confirmation and are backed up before replacement.
6. Optionally choose **Export JPEG** for FramePilot-rendered output.

## XMP design and Adobe validation

FramePilot writes RDF/XML using Adobe's Camera Raw namespace, `http://ns.adobe.com/camera-raw-settings/1.0/`. The fields include `ProcessVersion`, `Version`, `Exposure2012`, the 2012 tonal controls, Texture, Clarity2012, Dehaze, Vibrance, Saturation, white balance, sharpening, and noise reduction. Process Version 6 was introduced with Camera Raw 15.4, so this MVP uses `crs:ProcessVersion="15.4"` as a conservative baseline. It deliberately omits masks, profile payloads, and tone curves rather than writing guessed data.

`*.xmp` is written beside the source using the source stem (for example, `IMG_0042.CR3` → `IMG_0042.xmp`). Adobe normally embeds metadata into DNG; FramePilot instead emits an external DNG sidecar to honor the no-source-modification rule. Recent Lightroom Classic releases can also create an additional `.acr` sidecar for heavy edits; FramePilot does not generate that newer binary/opaque payload.

Automated checks validate XML parsing, required namespaces/fields, value types/ranges, preservation of unrelated RDF attributes, atomic replacement behavior, and internal round-tripping. They do **not** prove visual or catalog interoperability.

Manual Adobe compatibility fixture workflow:

1. Copy one personally owned RAW file to a temporary directory; a synthetic byte fixture is insufficient because Adobe must recognize the camera format.
2. Import it into a new Lightroom Classic test catalog (or open it in Camera Raw).
3. In FramePilot, apply conspicuous representative values such as Exposure `+1.15`, Highlights `-44`, Shadows `+31`, custom Temperature `4850`, and Tint `+9`; export XMP.
4. In Lightroom Classic choose **Metadata → Read Metadata from File**, or reopen the file in Camera Raw.
5. Verify each supported Basic/Detail control, check that unrelated title/copyright metadata remains, and visually compare only as an Adobe-rendered reference.
6. Save metadata back from Adobe and diff the resulting XMP. Run `python scripts\validate_xmp.py path\to\file.xmp` against both files.

Until that matrix is exercised against supported Lightroom Classic/Camera Raw versions, FramePilot claims structurally valid Adobe Camera Raw XMP—not verified full Lightroom compatibility.

Adobe references used for the mapping:

- [Camera Raw XMP namespace](https://developer.adobe.com/xmp/docs/xmp-namespaces/crs/)
- [Camera Raw process versions](https://helpx.adobe.com/camera-raw/desktop/get-started/overview-and-setup/process-versions.html)
- [Lightroom sidecar behavior](https://helpx.adobe.com/lightroom-classic/desktop/organize-photos-in-lightroom-classic/metadata-basics-actions.html)

## Tests and checks

```powershell
python -m pytest
python -m compileall -q framepilot tests scripts
python scripts\validate_xmp.py path\to\IMG_0042.xmp
```

Tests create only synthetic RGB images and placeholder RAW paths; no copyrighted photographs are redistributed.

## Packaging

```powershell
.\scripts\package_windows.ps1
```

This produces a one-folder build under `dist\FramePilot`. A one-folder bundle is intentional: LibRaw/rawpy and Qt plugins are easier to diagnose and update than in a one-file executable. Test the output on a clean Windows 10 and Windows 11 VM before distribution. Code signing and an installer are not included yet.

## Privacy and logs

All processing is local. Logs go to `%LOCALAPPDATA%\FramePilot\logs\framepilot.log`; routine logs avoid full image metadata. Thumbnail cache can be removed safely and will be rebuilt. Project files and XMP sidecars remain user-controlled.

## Known MVP limitations and roadmap

- The renderer is intentionally approximate and not colourimetric parity with Adobe; camera profiles, display soft-proofing, masks, lens correction, and an editable tone curve remain future work.
- RAW metadata extraction is best-effort because embedded JPEG EXIF is inconsistent. A direct, argument-safe ExifTool adapter is the next metadata task.
- Similarity grouping compares only a bounded capture-order window, preventing quadratic work but potentially missing distant duplicates.
- “AI culling” currently means explainable deterministic CV heuristics. No neural model, face analysis, closed-eye detection, semantic search, or event-category recognition is claimed.
- The contact sheet does not virtualize millions of items; thumbnail decoding is lazy/backgrounded, but a model/view replacement is recommended for very large shoots.
- Adobe 2025+ `.acr` sidecars are not generated. XMP remains the interoperable metadata container for the supported control subset.
- Highest priority next: validate XMP round-trips in current Lightroom Classic and Camera Raw with representative camera files, then lock version-specific fixtures.

