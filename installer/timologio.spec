# PyInstaller spec — χτίζει τον φάκελο dist/TimologioDownloader.
#
# Χτίζουμε one-dir (όχι one-file): το one-file ξεπακετάρει ~200MB Qt σε προσωρινό
# φάκελο σε κάθε εκκίνηση, που είναι αργό και σκοντάφτει σε antivirus. Ο Inno
# Setup αναλαμβάνει τη διανομή, οπότε ο χρήστης δεν βλέπει ποτέ τον φάκελο.
#
# Χρήση:  uv run pyinstaller installer/timologio.spec --noconfirm

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Το tzdata είναι πακέτο μόνο-δεδομένων: το zoneinfo το βρίσκει με
# importlib.resources, κάτι που το PyInstaller δεν μπορεί να δει διαβάζοντας
# imports. Χωρίς αυτό, το ZoneInfo("Europe/Athens") σκάει μέσα στο bundle και το
# αρχείο καταγραφής γυρίζει σιωπηλά σε ώρα μηχανήματος.
TZDATA = collect_data_files("tzdata")

# Το SPECPATH είναι ο φάκελος installer/· τα πάντα αλλιώς λύνονται σχετικά με
# αυτόν και όχι με τη ρίζα του έργου.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "entry.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    # Το εικονίδιο μπαίνει και ως δεδομένο, όχι μόνο στο exe: το παράθυρο το
    # φορτώνει κατά την εκτέλεση (gui/app.py:app_icon) για τη γραμμή εργασιών.
    # Το logo.svg το ζωγραφίζει το πλαϊνό μενού (gui/icons.py:logo_pixmap).
    datas=[
        (path, ".")
        for path in (ICON, os.path.join(SPECPATH, "logo.svg"))
        if os.path.exists(path)
    ] + TZDATA,
    # websocket-client (import name «websocket») το φορτώνει το headless module
    # με τοπικό import, οπότε το PyInstaller δεν το βλέπει από το στατικό δέντρο.
    hiddenimports=(
        collect_submodules("timologio")
        + collect_submodules("websocket")
        + ["tzdata"]
    ),
    hookspath=[],
    runtime_hooks=[],
    # Ό,τι σέρνει το PySide6 και δεν χρησιμοποιούμε. Χωρίς αυτό ο φάκελος
    # φτάνει τα ~450MB· έτσι μένει κάτω από ~120MB.
    excludes=[
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
        "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtTest",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets", "PySide6.QtSql", "PySide6.QtPdfWidgets",
        # ΣΗΜ.: το PySide6.QtPdf ΔΕΝ εξαιρείται πλέον — το χρειάζεται η μαζική
        # εκτύπωση (gui/printing.py) για να αποδώσει τα PDF στον εκτυπωτή.
        "tkinter", "matplotlib", "numpy", "pandas", "PIL", "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TimologioDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI app — χωρίς μαύρο παράθυρο κονσόλας
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.exists(ICON) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TimologioDownloader",
)
