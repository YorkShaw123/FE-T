# -*- coding: utf-8 -*-
"""检查数据库中是否包含敏感信息"""
import sqlite3

conn = sqlite3.connect(r'D:\Forestar_Editior2\data\forestar.db')
conn.row_factory = sqlite3.Row

# 1. 列出所有表
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print('=== 表列表 ===')
print(tables)

# 2. 检查每张表是否包含 key/token/secret 相关列
for t in tables:
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({t})')]
    sensitive = [c for c in cols if any(k in c.lower() for k in ('key', 'token', 'secret', 'password', 'credential'))]
    if sensitive:
        print(f'表 {t} 含敏感列: {sensitive}')
        try:
            rows = conn.execute(f'SELECT {",".join(sensitive)} FROM {t}').fetchall()
            for r in rows[:5]:
                print('   ', dict(r))
        except Exception as e:
            print('   读取失败:', e)

# 3. 统计各表行数
print('\n=== 各表行数 ===')
for t in tables:
    try:
        n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'{t}: {n}')
    except Exception as e:
        print(f'{t}: 读取失败 {e}')

conn.close()
