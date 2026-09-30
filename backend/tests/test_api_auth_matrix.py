"""接口鉴权矩阵集成测试。

覆盖核心链路的鉴权边界，针对三类身份（非认证 / 普通用户 / 管理员）验证
受保护端点的访问控制，并验证公开端点无需 token 即可访问。

设计要点：
- 通过在 import app 前设置固定的 SECRET_KEY，确保测试中签发的 JWT 可被验证
  （config._get_secret() 在未配置 SECRET_KEY 时每次调用生成随机密钥）。
- SQLite 无法原生编译 PostgreSQL 特有的 ARRAY 类型，注册测试本地的
  @compiles(ARRAY, "sqlite") 变体（渲染为 JSON）以支持离线建表。
- get_db 依赖通过 app.dependency_overrides 替换为绑定 SQLite 的会话，
  因此走 app 现有的依赖注入链路（get_current_user 也复用该 override）。
- Celery 任务（process_literature.delay）被 monkeypatch 为 no-op，保证离线。
"""
import os
import re
import sqlite3

# 必须在导入 app（进而导入 config/settings）之前注入固定密钥，
# 否则 config._get_secret() 每次调用返回随机值，token 签/验不一致导致 401。
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdef-0123456789abcdef-0123456789abcdef"


def _register_pg_sqlite_functions(raw: sqlite3.Connection) -> None:
    """在 SQLite 连接上注册 PostgreSQL 常用函数。

    ``literature.title_norm`` 生成列使用 ``btrim`` / ``regexp_replace``（PG 专用），
    SQLite 原生不支持；此处注册等价实现，使 ``Base.metadata.create_all`` 可离线建表。
    """

    def btrim1(s):
        return (s or "").strip()

    def btrim2(s, chars):
        return (s or "").strip(chars) if s is not None else s

    def regexp_replace_impl(s, pattern, replacement, flags="", count=0):
        if s is None:
            return None
        n = 0 if "g" in (flags or "") else 1
        return re.sub(pattern, replacement, s, count=n)

    raw.create_function("btrim", 1, btrim1, deterministic=True)
    raw.create_function("btrim", 2, btrim2, deterministic=True)
    raw.create_function(
        "regexp_replace", 3, lambda s, p, r: regexp_replace_impl(s, p, r), deterministic=True
    )
    raw.create_function(
        "regexp_replace", 4, lambda s, p, r, f: regexp_replace_impl(s, p, r, f), deterministic=True
    )


# aiosqlite 在后台线程调用模块级 sqlite3.connect()，因此在此处全局打补丁，
# 使本模块内创建的每个 SQLite 连接都自动注册上述 PG 函数。
_orig_sqlite3_connect = sqlite3.connect


def _patched_sqlite3_connect(*args, **kwargs):
    conn = _orig_sqlite3_connect(*args, **kwargs)
    _register_pg_sqlite_functions(conn)
    return conn


sqlite3.connect = _patched_sqlite3_connect

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport
from sqlalchemy import ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# SQLite 将 PostgreSQL 专用类型渲染为通用类型，从而允许 Base.metadata.create_all 离线建表。
@compiles(ARRAY, "sqlite")
def _compile_array(sqlite_compiler, column, **kw):  # pragma: no cover - 编译器钩子
    return "JSON"


@compiles(JSONB, "sqlite")
def _compile_jsonb(sqlite_compiler, column, **kw):  # pragma: no cover - 编译器钩子
    return "JSON"


@compiles(PostgresUUID, "sqlite")
def _compile_pg_uuid(sqlite_compiler, column, **kw):  # pragma: no cover - 编译器钩子
    return "CHAR(32)"


from app.main import app  # noqa: E402  必须在 SECRET_KEY 注入后导入
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.api.deps import get_db  # noqa: E402

# Celery 任务占位：测试中不真正派发异步任务，仅校验链路。
# 通过 monkeypatch 掉 extraction_service 中导入的 task，避免连 Redis broker。
import app.services.extraction_service as extraction_service_mod  # noqa: E402


def _fake_task():
    """返回带 .delay 的假任务对象，delay 为 no-op。"""
    class _Fake:
        def delay(self, **kw):
            return None

    return _Fake()


@pytest.fixture
def disable_celery(monkeypatch):
    """将 process_literature.delay 替换为 no-op，确保离线运行。"""
    from app.tasks.extract_task import process_literature  # 确保对象已导入
    monkeypatch.setattr(extraction_service_mod, "process_literature", _fake_task())
    yield process_literature


@pytest.fixture(scope="module", autouse=True)
def _real_auth_for_matrix():
    """本模块测试的是真实鉴权边界，需绕开 conftest 注入的假管理员。

    conftest 的 session 级 autouse 夹具把 get_current_user 覆盖为返回假管理员，
    会掩盖 401 校验（未认证请求也会被当作已认证返回 200）。本模块需恢复真实的
    JWT 鉴权链路，并 mock 掉 Redis 吊销检查（fail-closed，离线环境无 Redis）。

    模块结束后恢复原覆盖，避免影响后续依赖假管理员的 API 测试。
    """
    from app.api import deps as api_deps

    original_user_override = app.dependency_overrides.get(api_deps.get_current_user)
    app.dependency_overrides.pop(api_deps.get_current_user, None)

    orig_is_token_revoked = api_deps.is_token_revoked
    orig_pwd_check = api_deps.token_issued_before_password_change

    async def _no_revoke(jti):  # noqa: ANN001
        return False

    api_deps.is_token_revoked = _no_revoke
    api_deps.token_issued_before_password_change = lambda iat, pwd: False  # noqa: ARG005

    yield

    api_deps.is_token_revoked = orig_is_token_revoked
    api_deps.token_issued_before_password_change = orig_pwd_check
    if original_user_override is not None:
        app.dependency_overrides[api_deps.get_current_user] = original_user_override


@pytest_asyncio.fixture(loop_scope="function")
async def db_env():
    """在内存 SQLite 上建表并写入测试用户，然后把 get_db 覆盖到该会话。

    返回 tokens：{normal, admin}，分别对应普通用户和管理员的 JWT。
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        # 普通用户
        normal = User(username="normal_user", hashed_password="x", is_active=True, is_admin=False)
        session.add(normal)
        # 管理员
        admin = User(username="admin_user", hashed_password="x", is_active=True, is_admin=True)
        session.add(admin)
        # 可用于 /auth/login 校验口令的用户
        login_user = User(
            username="login_user",
            hashed_password=hash_password("Test@1234"),
            is_active=True,
            is_admin=False,
        )
        session.add(login_user)
        await session.commit()
        await session.refresh(normal)
        await session.refresh(admin)
        await session.refresh(login_user)

    async def override_get_db():
        async with SessionLocal() as s:
            yield s

    app.dependency_overrides[get_db] = override_get_db

    tokens = {
        "normal": create_access_token(str(normal.id), normal.username, normal.is_admin),
        "admin": create_access_token(str(admin.id), admin.username, admin.is_admin),
    }

    try:
        yield tokens
    finally:
        # 只移除本夹具注入的 get_db，避免 clear() 误删 conftest/其他夹具的覆盖
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="function")
async def client():
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── 受保护端点鉴权矩阵 ────────────────────────────────

# 端点 -> (method, 请求构造器)
# 身份期望：None=非认证(401)，normal/admin=200（这些端点仅要求登录，非管理员专属）
_PROTECTED_CASES = [
    ("extraction_batch", "post", "/api/v1/literatures/extraction/batch"),
    ("report_templates", "get", "/api/v1/report/templates"),
    ("analysis_review_stats", "get", "/api/v1/analysis/review-stats"),
]


class TestProtectedEndpointsAuthMatrix:
    @pytest.mark.asyncio(loop_scope="function")
    @pytest.mark.parametrize(
        "endpoint, method, url",
        _PROTECTED_CASES,
        ids=[c[0] for c in _PROTECTED_CASES],
    )
    async def test_unauthenticated_gives_401(self, client, db_env, endpoint, method, url):
        if method == "post":
            resp = await client.post(url, json={"literature_ids": ["00000000-0000-0000-0000-000000000000"]})
        else:
            resp = await client.get(url)
        assert resp.status_code == 401, f"{url} 应在未认证时返回 401，实际 {resp.status_code}"

    @pytest.mark.asyncio(loop_scope="function")
    @pytest.mark.parametrize(
        "endpoint, method, url",
        _PROTECTED_CASES,
        ids=[c[0] for c in _PROTECTED_CASES],
    )
    async def test_normal_user_authenticated(self, client, db_env, disable_celery, endpoint, method, url):
        tokens = db_env
        headers = _auth_headers(tokens["normal"])
        if method == "post":
            resp = await client.post(url, json={"literature_ids": ["00000000-0000-0000-0000-000000000000"]}, headers=headers)
        else:
            resp = await client.get(url, headers=headers)
        assert resp.status_code == 200, f"{url} 普通用户应可访问(200)，实际 {resp.status_code}"

    @pytest.mark.asyncio(loop_scope="function")
    @pytest.mark.parametrize(
        "endpoint, method, url",
        _PROTECTED_CASES,
        ids=[c[0] for c in _PROTECTED_CASES],
    )
    async def test_admin_authenticated(self, client, db_env, disable_celery, endpoint, method, url):
        tokens = db_env
        headers = _auth_headers(tokens["admin"])
        if method == "post":
            resp = await client.post(url, json={"literature_ids": ["00000000-0000-0000-0000-000000000000"]}, headers=headers)
        else:
            resp = await client.get(url, headers=headers)
        assert resp.status_code == 200, f"{url} 管理员应可访问(200)，实际 {resp.status_code}"


# ── 公开端点无需 token ────────────────────────────────

class TestPublicEndpoints:
    @pytest.mark.asyncio(loop_scope="function")
    async def test_health_public(self, client, db_env):
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "antibody-map-api"

    @pytest.mark.asyncio(loop_scope="function")
    async def test_login_public(self, client, db_env):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "login_user", "password": "Test@1234"},
        )
        assert resp.status_code == 200, f"登录应无需 token 即可访问，实际 {resp.status_code}"
        body = resp.json()
        assert body["success"] is True
        assert (token := body["data"]["token"])

    @pytest.mark.asyncio(loop_scope="function")
    async def test_batch_extraction_rejects_empty_list_once_authenticated(self, client, db_env, disable_celery):
        """认证通过后，参数校验仍生效（空列表 -> 400），证明依赖链路完整。"""
        tokens = db_env
        resp = await client.post(
            "/api/v1/literatures/extraction/batch",
            json={"literature_ids": []},
            headers=_auth_headers(tokens["normal"]),
        )
        assert resp.status_code == 400