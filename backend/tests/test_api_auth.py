"""api/v1/auth.py 端点测试。"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.user import User


def _fake_db():
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalars = MagicMock(return_value=fake_result)
    fake_result.all = MagicMock(return_value=[])
    fake_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=fake_result)
    db.commit = AsyncMock()
    db.delete = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


def _fake_user(is_admin=False, user_id="11111111-1111-1111-1111-111111111111"):
    u = User(
        id=user_id,
        username="admin" if is_admin else "user",
        display_name="管理员" if is_admin else "普通用户",
        is_admin=is_admin, is_active=True,
        hashed_password="__unused__",
    )
    u.created_at = datetime(2024, 1, 1, 12, 0, 0)
    return u


@pytest.mark.asyncio
async def test_list_users():
    from app.api.v1 import auth
    resp = await auth.list_users(admin=_fake_user(is_admin=True), db=_fake_db())
    assert resp.data == []


@pytest.mark.asyncio
async def test_get_me():
    from app.api.v1 import auth
    resp = await auth.get_me(user=_fake_user())
    assert resp.data.username == "user"


@pytest.mark.asyncio
async def test_logout_no_auth():
    from app.api.v1 import auth
    resp = await auth.logout(authorization=None, user=_fake_user(), db=_fake_db())
    assert resp.message is not None


@pytest.mark.asyncio
async def test_change_password_success():
    from app.api.v1 import auth
    req = MagicMock()
    req.old_password = "oldpass123"
    req.new_password = "NewPass123!"
    with patch("app.api.v1.auth.verify_password", return_value=True):
        resp = await auth.change_password(req=req, user=_fake_user(), db=_fake_db())
    assert "成功" in resp.message


@pytest.mark.asyncio
async def test_login_bad_password_401():
    from app.api.v1 import auth
    req = MagicMock()
    req.username = "nobody"
    req.password = "xyz"
    fake_request = MagicMock(spec=Request)
    with pytest.raises(HTTPException) as exc:
        await auth.login(req=req, request=fake_request, db=_fake_db())
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_delete_user_success_not_self():
    from app.api.v1 import auth
    admin = _fake_user(is_admin=True, user_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    target = _fake_user(is_admin=False, user_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    fake_execute = MagicMock()
    fake_execute.scalar_one_or_none = MagicMock(return_value=target)
    db = _fake_db()
    db.execute = AsyncMock(return_value=fake_execute)
    resp = await auth.delete_user(
        user_id=target.id, admin=admin, db=db,
    )
    assert "成功" in resp.message
