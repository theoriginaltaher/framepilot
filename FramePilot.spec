# Optional reproducible PyInstaller entrypoint; scripts/package_windows.ps1 is the primary packaging command.
from PyInstaller.utils.hooks import collect_all

rawpy_data, rawpy_bins, rawpy_hidden = collect_all("rawpy")

a = Analysis(["framepilot/main.py"], pathex=[], binaries=rawpy_bins, datas=rawpy_data,
             hiddenimports=rawpy_hidden, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FramePilot", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=True, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="FramePilot")
