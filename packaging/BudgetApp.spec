# PyInstaller build definition for the Windows desktop application.
from pathlib import Path

project_root = Path(SPECPATH).parent
source_root = project_root / "src"
package_root = source_root / "budget_app"

a = Analysis(
    [str(package_root / "__main__.py")],
    pathex=[str(source_root)],
    binaries=[],
    datas=[
        (str(package_root / "styles" / "theme.qss"), "budget_app/styles"),
        (str(package_root / "styles" / "checkbox.svg"), "budget_app/styles"),
        (str(package_root / "assets" / "BudgetApp.ico"), "budget_app/assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BudgetApp",
    icon=str(package_root / "assets" / "BudgetApp.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BudgetApp",
)
