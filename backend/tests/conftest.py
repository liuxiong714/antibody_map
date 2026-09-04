"""测试共享夹具：让基于 ASGITransport(app) 的 API 测试无需真实 DB/Redis/Ollama 即可运行。

通过 FastAPI app.dependency_overrides 将 get_db / get_current_user 替换为离网实现：
- get_db           -> 返回 MagicMock 会话（API 测试只校验路由契约，不落到真实库）
- get_current_user -> 返回假的系统管理员（绕过 JWT 校验与 Redis 吊销查询）

说明：httpx.ASGITransport 默认不触发 lifespan（不会跑 Alembic 迁移 / 后台任务），
且 SQLAlchemy 引擎为惰性创建，因此 import app.main 不会真的连接数据库。
"""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.api import deps
from app.models.user import User


async def _override_get_db():
    """离网 DB 会话：API 契约测试不真实查询数据库。"""
    yield MagicMock(spec=AsyncSession)


async def _override_get_current_user():
    """离网认证：返回假的系统管理员，不用 JWT/Redis。"""
    return User(
        id="00000000-0000-0000-0000-000000000001",
        username="__test_admin__",
        display_name="测试管理员",
        is_active=True,
        is_admin=True,
        hashed_password="__unused__",
    )


@pytest.fixture(scope="session", autouse=True)
def _mock_external_dependencies():
    """Session 级自动夹具：安装依赖覆盖，测试结束时清理。

    仅对走真实 HTTP/ASGI 的测试生效；纯单元测试不触发 get_db/get_current_user，无副作用。
    """
    app.dependency_overrides[deps.get_db] = _override_get_db
    app.dependency_overrides[deps.get_current_user] = _override_get_current_user
    yield
    app.dependency_overrides.clear()