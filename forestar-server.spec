# -*- mode: python ; coding: utf-8 -*-
"""Forestar Editor 后端 PyInstaller 打包配置（单文件模式）。

用法：python -m PyInstaller forestar-server.spec --clean --noconfirm
产物：dist/forestar-server.exe（Windows）
"""
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# 项目根目录（spec 所在目录）与后端代码目录 server/
ROOT = os.path.abspath(SPECPATH)
SERVER_DIR = os.path.join(ROOT, 'server')
# 让 collect_submodules 能按包名（services/routes）扫描到 server/ 下的模块
sys.path.insert(0, SERVER_DIR)

# 收集项目内部包的全部子模块，避免动态导入遗漏
hiddenimports = (
    collect_submodules('services')
    + collect_submodules('routes')
    + ['database', 'database.models', 'database.migrations']
)

a = Analysis(
    [os.path.join(SERVER_DIR, 'app.py')],
    pathex=[SERVER_DIR],
    binaries=[],
    datas=[
        # 静态资源与模板打进单文件；运行时从 sys._MEIPASS 解压读取（见 app.py 路径适配）
        (os.path.join(SERVER_DIR, 'templates'), 'templates'),
        (os.path.join(SERVER_DIR, 'static'), 'static'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除打包时不需要的框架与标准库，减小体积
        'tkinter',
        'pydoc',
        'pydoc_data',
        'lib2to3',
        'unittest',
        'setuptools',
        'pip',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='forestar-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # 关闭 UPX：PyInstaller 归档本身已做 zlib 压缩，UPX 对体积收益有限，
    # 却会提高杀软误报概率；关闭后误报率明显降低
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 打包为 GUI 程序，不弹出黑色控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=os.path.join(ROOT, 'forestar-version-info.txt'),  # 注入版本信息，降低误报
)
