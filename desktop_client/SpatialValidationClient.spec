# PyInstaller configuration for the desktop client.
from pathlib import Path

project = Path(SPECPATH)

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    datas=[(str(project / "config"), "config")],
    hiddenimports=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SpatialValidationClient",
    debug=False,
    strip=False,
    upx=True,
    console=False,
)
