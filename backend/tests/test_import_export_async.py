"""import_export.py async 函数测试 —— with patch 上下文。"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_db():
    db = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_literature(lit_id=uuid.UUID(int=1)):
    return SimpleNamespace(
        id=lit_id, title="Test Paper",
        file_path=None, pdf_hash=None, has_fulltext=False,
        authors=[], abstract=None, keywords=[],
        publication_date=None, journal=None, doi=None,
    )


# ===== upload_literature_file =====

@pytest.mark.asyncio
async def test_upload_literature_file_happy_path(tmp_path):
    from app.services.literature.import_export import upload_literature_file
    fake_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    with patch("app.services.literature.import_export.get_literature",
               AsyncMock(return_value=_make_literature())), \
         patch("app.services.literature.import_export.uuid.uuid4", return_value=fake_uuid), \
         patch("app.services.literature.import_export.upload_file", return_value="minio://ok"), \
         patch("app.services.literature.import_export.get_mime_type", return_value="application/pdf"), \
         patch("app.services.literature.import_export.compute_pdf_hash", return_value="fakehash123"), \
         patch("app.services.literature.import_export.LOCAL_STORAGE_DIR", tmp_path), \
         patch("os.remove"), \
         patch("app.services.literature.import_export.derive_minio_object_name", return_value=None):
        result = await upload_literature_file(
            db=_fake_db(), literature_id=uuid.UUID(int=1),
            file_bytes=b"%PDF-1.4 fake pdf", filename="test.pdf",
        )
    assert result is not None
    assert result.has_fulltext is True


@pytest.mark.asyncio
async def test_upload_literature_file_not_found(tmp_path):
    from app.services.literature.import_export import upload_literature_file
    with patch("app.services.literature.import_export.get_literature",
               AsyncMock(return_value=None)), \
         patch("app.services.literature.import_export.LOCAL_STORAGE_DIR", tmp_path):
        result = await upload_literature_file(
            db=_fake_db(), literature_id=uuid.UUID(int=999),
            file_bytes=b"%PDF-1.4", filename="x.pdf",
        )
    assert result is None


@pytest.mark.asyncio
async def test_upload_literature_file_minio_fails_still_ok(tmp_path):
    from app.services.literature.import_export import upload_literature_file
    fake_uuid = uuid.UUID("11111111-2222-3333-4444-555555555555")
    with patch("app.services.literature.import_export.get_literature",
               AsyncMock(return_value=_make_literature())), \
         patch("app.services.literature.import_export.uuid.uuid4", return_value=fake_uuid), \
         patch("app.services.literature.import_export.upload_file", return_value=None), \
         patch("app.services.literature.import_export.get_mime_type", return_value="application/pdf"), \
         patch("app.services.literature.import_export.compute_pdf_hash", return_value="h"), \
         patch("app.services.literature.import_export.LOCAL_STORAGE_DIR", tmp_path), \
         patch("os.remove"):
        result = await upload_literature_file(
            db=_fake_db(), literature_id=uuid.UUID(int=1),
            file_bytes=b"%PDF-1.4", filename="test.pdf",
        )
    assert result is not None


@pytest.mark.asyncio
async def test_upload_literature_file_has_old_file(tmp_path):
    lit = _make_literature()
    lit.file_path = str(tmp_path / "old.pdf")
    (tmp_path / "old.pdf").write_bytes(b"old content")
    from app.services.literature.import_export import upload_literature_file
    fake_uuid = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    with patch("app.services.literature.import_export.get_literature",
               AsyncMock(return_value=lit)), \
         patch("app.services.literature.import_export.uuid.uuid4", return_value=fake_uuid), \
         patch("app.services.literature.import_export.upload_file", return_value="minio://ok"), \
         patch("app.services.literature.import_export.get_mime_type", return_value="application/pdf"), \
         patch("app.services.literature.import_export.compute_pdf_hash", return_value="h"), \
         patch("app.services.literature.import_export.LOCAL_STORAGE_DIR", tmp_path), \
         patch("os.remove"), \
         patch("app.services.literature.import_export.derive_minio_object_name",
               return_value="literature/old.pdf"), \
         patch("app.services.literature.import_export.delete_file") as m_del:
        result = await upload_literature_file(
            db=_fake_db(), literature_id=uuid.UUID(int=1),
            file_bytes=b"%PDF-1.4", filename="new.pdf",
        )
    assert result is not None
    m_del.assert_called_once()


@pytest.mark.asyncio
async def test_upload_literature_file_db_commit_fails(tmp_path):
    from app.services.literature.import_export import upload_literature_file
    fake_db = _fake_db()
    fake_db.commit = AsyncMock(side_effect=Exception("db down"))
    fake_uuid = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    with patch("app.services.literature.import_export.get_literature",
               AsyncMock(return_value=_make_literature())), \
         patch("app.services.literature.import_export.uuid.uuid4", return_value=fake_uuid), \
         patch("app.services.literature.import_export.upload_file", return_value="minio://ok"), \
         patch("app.services.literature.import_export.get_mime_type", return_value="application/pdf"), \
         patch("app.services.literature.import_export.compute_pdf_hash", return_value="h"), \
         patch("app.services.literature.import_export.LOCAL_STORAGE_DIR", tmp_path), \
         patch("os.remove"):
        result = await upload_literature_file(
            db=fake_db, literature_id=uuid.UUID(int=1),
            file_bytes=b"%PDF-1.4", filename="test.pdf",
        )
    assert result is None


@pytest.mark.asyncio
async def test_upload_literature_file_local_save_fails(tmp_path):
    """mkdir 或 open 抛异常 → 返回 None。"""
    from app.services.literature.import_export import upload_literature_file
    fake_uuid = uuid.UUID("00000000-1111-2222-3333-444444444444")
    with patch("app.services.literature.import_export.get_literature",
               AsyncMock(return_value=_make_literature())), \
         patch("app.services.literature.import_export.uuid.uuid4", return_value=fake_uuid), \
         patch("app.services.literature.import_export.LOCAL_STORAGE_DIR", tmp_path), \
         patch("builtins.open", side_effect=PermissionError("no write")):
        result = await upload_literature_file(
            db=_fake_db(), literature_id=uuid.UUID(int=1),
            file_bytes=b"%PDF-1.4", filename="test.pdf",
        )
    assert result is None
