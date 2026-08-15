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
BUNDLE_LOCAL_EMBEDDING = os.environ.get('FORESTAR_BUNDLE_ONNX') == '1'

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
        # 排除打包时不需要的框架与标准库，减小体积与启动解压耗时
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
        # numpy 只在向量检索/索引时延迟导入；排除其测试与编译子模块（体积大头之一）
        'numpy.testing',
        'numpy.f2py',
        'numpy.distutils',
        'numpy.typing',
        # 以下子模块位于 numpy/__init__.py 的 __getattr__ 延迟加载中，
        # 项目代码从不访问 np.random/np.fft/np.ma 等，排除后运行不受影响，
        # 可减小 numpy.random 的 .pyd（约 1.2MB）与 numpy.fft 等打包体积。
        'numpy.random',
        'numpy.fft',
        'numpy.ma',
        'numpy.polynomial',
        'numpy.ctypeslib',
        'numpy.matlib',
        'numpy.char',
        'numpy.rec',
        # SQLAlchemy 仅使用 SQLite 方言，排除其他方言（均为延迟导入，排除安全）
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
        # openai/httpx 的可选 extras（websocket/代理/压缩/REPL 增强等）
        'websockets',
        'sounddevice',
        'pandas',
        'watchdog',
        'brotli',
        'brotlicffi',
        'zstandard',
        'trio',
        'uvloop',
        'winloop',
        'h2',
        'socksio',
        'rich',
        'pygments',
        'IPython',
        # openai SDK 依赖链已整体移除（api_client 改为标准库 urllib 实现）：
        # 排除 SDK 本体及其依赖，避免体积 15~20MB 的白白打包。
        # 全项目已无任何代码 import 这些模块（已逐一确认），排除安全。
        'openai',
        'pydantic',
        'pydantic_core',
        'httpx',
        'httpcore',
        'jiter',
        'cryptography',
        'dotenv',
        'anyio',
        'sniffio',
        'h11',
        'certifi',
        'idna',
        'distro',
        'tiktoken',
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
