# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 - B站数字卡片抢购工具 GUI 版

关键优化：
1. console=False  → 消除额外的命令行黑窗口（使用 Windows GUI 子系统）
2. onedir 模式    → 启动快（无需解压到临时目录）
3. 排除 rich 模块 → 减小包体积（GUI 不依赖 rich）
"""

import os

# ── 需要打包的数据文件 ──────────────────────────────────────────
# 注意：config.json 和 cookies.json 放在可执行文件同级目录
datas = []
data_files = ["config.json", "cookies.json"]
# SPECPATH 是 PyInstaller 提供的 spec 文件所在目录
spec_dir = os.path.dirname(os.path.abspath(SPECPATH))
for f in data_files:
    src = os.path.join(spec_dir, f)
    if os.path.exists(src):
        datas.append((src, "."))

# ── 隐式导入（延迟导入的模块 PyInstaller 可能检测不到） ─────────
hiddenimports = [
    "httpx",
    "httpx._config",
    "httpx._client",
    "httpx._models",
    "httpx._transports",
    "requests",
    "httpcore",
    "h11",
    "h2",
    "anyio",
    "certifi",
    "charset_normalizer",
    "idna",
    "urllib3",
    "json",
]

# ── 排除模块（GUI 不需要的，减小体积） ──────────────────────────
excludes = [
    "rich",
    "rich.console",
    "rich.panel",
    "rich.table",
    "rich.prompt",
    "rich.layout",
    "rich.live",
    "rich.text",
    "rich.box",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "tkinter.test",
    "tkinter.tix",
    "lib2to3",
    "test",
    "unittest",
    "pdb",
    "doctest",
]

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure)

# ── EXE 配置 ────────────────────────────────────────────────────
# console=False → 不弹出命令行窗口（关键修复！）
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="biliskin-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,       # 移除调试符号，减小体积
    upx=False,        # 禁用 UPX 压缩（加快启动速度）
    console=False,    # ★ 关键：不弹出命令行窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,        # 如需自定义图标：icon="icon.ico"
)

# ── COLLECT（onedir 模式） ──────────────────────────────────────
# onedir 模式：生成一个文件夹，exe 和依赖放在一起
# 启动时无需解压，比 onefile 快 3-5 倍
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="biliskin-gui",
)
