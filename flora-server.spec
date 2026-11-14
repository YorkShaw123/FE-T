# -*- mode: python ; coding: utf-8 -*-
"""Flora Editor 后端 PyInstaller 打包配置（单文件模式）。

用法：python -m PyInstaller flora-server.spec --clean --noconfirm
产物：dist/flora-server.exe（Windows）

入口已切换到 ``run_server.py``（FastAPI + Agent 架构）。与旧版 spec 的差别：
- 后端代码从 ``server/`` 换成 ``backend/``，需要收集 backend 全部子模块；
- 不再排除 pydantic / httpx / anyio 等库——FastAPI 与 LangChain 依赖它们；
- 静态资源与模板仍打进包里，但保留 ``server/`` 前缀，因为
  ``backend.config.PROJECT_ROOT`` 在冻结环境下解析到 ``sys._MEIPASS``。
"""

import os

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(SPECPATH)
SERVER_DIR = os.path.join(ROOT, 'server')
BUNDLE_LOCAL_EMBEDDING = os.environ.get('FLORA_BUNDLE_ONNX') == '1'

hiddenimports = (
    collect_submodules('backend')
    + [
        'backend.main',
        'backend.db.migrations',
        'backend.agents.writing.graph',
        'backend.agents.style_qa.graph',
        'backend.agents.consistency.graph',
        # uvicorn 的启动器按字符串动态导入，需显式声明
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan.on',
        'aiosqlite',
    ]
)

a = Analysis(
    [os.path.join(ROOT, 'run_server.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(SERVER_DIR, 'templates'), 'server/templates'),
        (os.path.join(SERVER_DIR, 'static'), 'server/static'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'pydoc',
        'pydoc_data',
        'lib2to3',
        'unittest',
        'setuptools',
        'pip',
        'pdb',
        'doctest',
        'test',
        # numpy 只用于向量检索，其测试与编译辅助模块可排除
        'numpy.testing',
        'numpy.f2py',
        'numpy.distutils',
        # 仅使用 SQLite 方言
        'psycopg2',
        'psycopg',
        'asyncpg',
        'pymysql',
        'MySQLdb',
        'mysql',
        'asyncmy',
        'cx_Oracle',
        'oracledb',
        'sqlcipher3',
        'pysqlcipher3',
        # 语音/数据/可视化等无关重包
        'sounddevice',
        'pandas',
        'matplotlib',
        'notebook',
        'IPython',
        'rich',
        'pygments',
    ] + ([] if BUNDLE_LOCAL_EMBEDDING else ['onnxruntime']),
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='flora-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon=os.path.join(ROOT, 'src-tauri', 'icons', 'icon.ico'),
    codesign_identity=None,
    entitlements_file=None,
    version=os.path.join(ROOT, 'flora-version-info.txt'),
)
