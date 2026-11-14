"""Flora Editor 后端（Agent 架构）。

迁移期与旧的 ``server/`` 包并存：``server/`` 继续提供 Flask 服务，
``backend/`` 逐步接管路由与 Agent 编排，直到验收通过后退役旧包。

分层（自外向内）::

    api  →  agents  →  core  →  db
                  ↘  services  ↗
            adapters  ←  core
"""

__version__ = "1.1.0"
