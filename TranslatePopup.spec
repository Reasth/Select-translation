# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件、窗口程序、极致瘦身。

瘦身手段：
1. 只保留用到的 QtCore/QtGui/QtWidgets，排除其余 31 个 Qt 模块（QtWebEngine /
   QtQml / QtMultimedia / QtPdf … 单个就好几十 MB）。
2. 排除 tkinter / 测试框架 / 旧 httpx 依赖链等无关包。
3. UPX 压缩（装了 upx 才生效；没装会自动跳过）。

构建：python -m PyInstaller --noconfirm TranslatePopup.spec
产物：dist/TranslatePopup.exe（Windows）/ dist/TranslatePopup.app（macOS）
"""

# 只保留这三个 Qt 模块，其余全部排除。
_QT_KEEP = {"QtCore", "QtGui", "QtWidgets"}
_QT_ALL = [
    "QtBluetooth", "QtCore", "QtDBus", "QtDesigner", "QtGui", "QtHelp",
    "QtMultimedia", "QtMultimediaWidgets", "QtNetwork", "QtNfc", "QtOpenGL",
    "QtOpenGLWidgets", "QtPdf", "QtPdfWidgets", "QtPositioning",
    "QtPrintSupport", "QtQml", "QtQuick", "QtQuick3D", "QtQuickWidgets",
    "QtRemoteObjects", "QtSensors", "QtSerialPort", "QtSpatialAudio", "QtSql",
    "QtStateMachine", "QtSvg", "QtSvgWidgets", "QtTest", "QtTextToSpeech",
    "QtWebChannel", "QtWebSockets", "QtXml",
]
_qt_excludes = [f"PyQt6.{m}" for m in _QT_ALL if m not in _QT_KEEP]

_other_excludes = [
    "tkinter", "test", "unittest", "pydoc_data", "lib2to3", "distutils",
    "setuptools", "pip", "ensurepip", "xmlrpc", "sqlite3",
    # 已弃用的 httpx 依赖链，确保不被误打进来
    "httpx", "httpcore", "anyio", "certifi", "h11", "h2", "idna", "sniffio",
    # 常见体积大户，本项目用不到
    "numpy", "PIL", "matplotlib", "pandas",
]

_upx_exclude = [
    "vcruntime140.dll", "vcruntime140_1.dll", "python3.dll", "python312.dll",
    "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
]

import os
import sys

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/tray.png", "assets")],
    hiddenimports=["ssl", "_ssl"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_qt_excludes + _other_excludes,
    noarchive=False,
)

# 用不到的 Qt 插件、translations、QtNetwork 残留 DLL 进一步剔除。
# 保留：platforms(qwindows.dll)、styles、platformthemes、xcbglintegrations(non-win 无影响)。
_PLUGIN_KILL_PATHS = (
    "PyQt6/Qt6/plugins/imageformats",
    "PyQt6/Qt6/plugins/iconengines",
    "PyQt6/Qt6/plugins/networkinformation",
    "PyQt6/Qt6/plugins/tls",
    "PyQt6/Qt6/plugins/generic",
    "PyQt6/Qt6/plugins/sqldrivers",
    "PyQt6/Qt6/plugins/multimedia",
    "PyQt6/Qt6/plugins/printsupport",
    "PyQt6/Qt6/plugins/sceneparsers",
    "PyQt6/Qt6/translations",
)
_DLL_KILL_NAMES = (
    "qt6network", "qt6qml", "qt6quick", "qt6quickwidgets",
    "qt6sql", "qt6test", "qt6pdf", "qt6opengl", "qt6printsupport",
    "qt6multimedia", "qt6svg", "qt6dbus", "qt6designercomponents",
    "libegl", "libgles",  # GL ES，PyQt6 在 Windows 上不一定真需要
)


def _norm(s):
    return s.replace("\\", "/").lower()


def _prune(seq):
    out = []
    for item in seq:
        name = _norm(item[0])
        src = _norm(item[1]) if len(item) > 1 and item[1] else ""
        if any(p.lower() in name or p.lower() in src for p in _PLUGIN_KILL_PATHS):
            continue
        base = name.rsplit("/", 1)[-1]
        if any(base.startswith(d) for d in _DLL_KILL_NAMES):
            continue
        out.append(item)
    return out


def _prefer_env_library_bin(seq):
    """Prefer DLLs from the Python env being packaged, not another conda on PATH."""
    if sys.platform != "win32":
        return seq
    env_bin = os.path.join(sys.prefix, "Library", "bin")
    if not os.path.isdir(env_bin):
        return seq
    out = []
    for item in seq:
        if len(item) < 3 or not item[1]:
            out.append(item)
            continue
        base = os.path.basename(item[1])
        replacement = os.path.join(env_bin, base)
        if os.path.exists(replacement):
            out.append((item[0], replacement, *item[2:]))
        else:
            out.append(item)
    return out


a.binaries = _prune(a.binaries)
a.binaries = _prefer_env_library_bin(a.binaries)
a.datas = _prune(a.datas)

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS：onedir + BUNDLE → 规范的 .app（onefile 与 .app 安全模型冲突）。
    # 图标：用 build/AppIcon.icns（CI 会现场生成占位图标）。必须给真实存在的
    # .icns，否则 PyInstaller 在 BUNDLE 阶段会去找默认 icns 并 FileNotFoundError。
    import os as _os
    _icns = _os.path.join("build", "AppIcon.icns")
    _mac_icon = _icns if _os.path.exists(_icns) else None
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="TranslatePopup",
        debug=False,
        strip=False,
        upx=True,
        upx_exclude=_upx_exclude,
        icon=_mac_icon,
        console=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=_upx_exclude,
        name="TranslatePopup",
    )
    app = BUNDLE(
        coll,
        name="TranslatePopup.app",
        icon=_mac_icon,
        bundle_identifier="com.translatepopup.app",
        info_plist={
            "LSUIElement": True,  # 纯菜单栏应用，不占 Dock
            "NSHighResolutionCapable": True,
        },
    )
else:
    # Windows / Linux：单文件 exe，便于分发。
    # 图标：用 build/AppIcon.ico（存在才设，避免本机没生成图标时打包失败）。
    import os as _os
    _ico = _os.path.join("build", "AppIcon.ico")
    _win_icon = _ico if _os.path.exists(_ico) else None
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="TranslatePopup",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=_upx_exclude,
        runtime_tmpdir=None,
        icon=_win_icon,
        console=False,
        disable_windowed_traceback=False,
    )
