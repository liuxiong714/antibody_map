"""api/v1/literature/import_export.py 端点测试 —— 全 patch service 层，无真实 DB/MinIO。"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from app.api.v1.literature import import_export as api
from app.models.user import User


# ====== export_literatures ======

@pytest.mark.asyncio
async def test_export_success():
    fake_payload = {
        "content": b"id,title\n1,hello",
        "media_type": "text/csv",
        "filename": "literatures.csv",
    }
    with patch("app.api.v1.literature.import_export.build_literatures_export",
               AsyncMock(return_value=fake_payload)):
        resp = await api.export_literatures(
            keyword=None, disease=None, province=None,
            year_start=None, year_end=None, journal=None,
            review_status=None, file_format=None, format="csv",
            include_data_points=False, literature_ids=None,
            db=MagicMock(),
        )
    assert resp.media_type == "text/csv"
    assert b"hello" in resp.body
    assert "literatures.csv" in resp.headers.get("Content-Disposition", "")


@pytest.mark.asyncio
async def test_export_value_error_400():
    with patch("app.api.v1.literature.import_export.build_literatures_export",
               AsyncMock(side_effect=ValueError("bad format"))):
        with pytest.raises(HTTPException) as exc:
            await api.export_literatures(
                keyword=None, disease=None, province=None,
                year_start=None, year_end=None, journal=None,
                review_status=None, file_format=None, format="xls",
                include_data_points=False, literature_ids=None,
                db=MagicMock(),
            )
    assert exc.value.status_code == 400
    assert "bad format" in exc.value.detail


# ====== import_literatures ======

@pytest.mark.asyncio
async def test_import_literatures_success():
    fake_file = UploadFile(filename="data.json", file=io.BytesIO(b'{"x":1}'))
    fake_result = {
        "imported_count": 5, "skipped_count": 2,
        "data_point_count": 10, "error_count": 0,
        "errors": [], "imported_titles": ["t1", "t2"],
    }
    with patch("app.api.v1.literature.import_export.import_literatures_from_json",
               AsyncMock(return_value=fake_result)):
        body = await api.import_literatures(fake_file, skip_duplicates=True, db=MagicMock())
    assert "5" in body.message
    assert body.data["imported_count"] == 5


@pytest.mark.asyncio
async def test_import_literatures_wrong_extension():
    fake_file = UploadFile(filename="data.xlsx", file=io.BytesIO(b"abc"))
    with pytest.raises(HTTPException) as exc:
        await api.import_literatures(fake_file, skip_duplicates=True, db=MagicMock())
    assert exc.value.status_code == 400
    assert "JSON" in exc.value.detail


@pytest.mark.asyncio
async def test_import_literatures_value_error_400():
    fake_file = UploadFile(filename="data.json", file=io.BytesIO(b"bad"))
    with patch("app.api.v1.literature.import_export.import_literatures_from_json",
               AsyncMock(side_effect=ValueError("invalid JSON"))):
        with pytest.raises(HTTPException) as exc:
            await api.import_literatures(fake_file, skip_duplicates=True, db=MagicMock())
    assert exc.value.status_code == 400
    assert "invalid JSON" in exc.value.detail


# ====== import_references_preview ======

@pytest.mark.asyncio
async def test_import_references_preview_success():
    fake_result = {"total": 10, "skipped": 2, "imported": 8}
    with patch("app.api.v1.literature.import_export.preview_import_references",
               AsyncMock(return_value=fake_result)):
        body = await api.import_references_preview(
            api.ImportReferencesBody(ref_text="TY  - JOUR...", fmt="auto"),
            db=MagicMock(),
        )
    assert "10" in body.message
    assert body.data["imported"] == 8


@pytest.mark.asyncio
async def test_import_references_preview_value_error_400():
    with patch("app.api.v1.literature.import_export.preview_import_references",
               AsyncMock(side_effect=ValueError("parse fail"))):
        with pytest.raises(HTTPException) as exc:
            await api.import_references_preview(
                api.ImportReferencesBody(ref_text="bad"), db=MagicMock(),
            )
    assert exc.value.status_code == 400


# ====== import_references ======

@pytest.mark.asyncio
async def test_import_references_success_with_log():
    fake_result = {"total": 10, "skipped": 2, "imported": 8, "errors": []}
    admin = User(id="00000000-0000-0000-0000-000000000001", username="admin",
                 is_admin=True, hashed_password="x")
    with patch("app.api.v1.literature.import_export.import_references_from_text",
               AsyncMock(return_value=fake_result)), \
         patch("app.api.v1.literature.import_export.create_import_log",
               AsyncMock()) as m_log:
        body = await api.import_references(
            api.ImportReferencesBody(ref_text="TY  - JOUR", fmt="auto",
                                     file_name="test.ris"),
            db=MagicMock(), current_user=admin,
        )
    assert "8" in body.message
    m_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_references_skip_log_does_not_call_create():
    fake_result = {"total": 1, "skipped": 0, "imported": 1, "errors": []}
    admin = User(id="00000000-0000-0000-0000-000000000001", username="admin",
                 is_admin=True, hashed_password="x")
    with patch("app.api.v1.literature.import_export.import_references_from_text",
               AsyncMock(return_value=fake_result)), \
         patch("app.api.v1.literature.import_export.create_import_log",
               AsyncMock()) as m_log:
        body = await api.import_references(
            api.ImportReferencesBody(ref_text="TY  - JOUR", fmt="auto",
                                     file_name="test.ris", skip_log=True),
            db=MagicMock(), current_user=admin,
        )
    m_log.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_references_value_error_400():
    admin = User(id="00000000-0000-0000-0000-000000000001", username="admin",
                 is_admin=True, hashed_password="x")
    with patch("app.api.v1.literature.import_export.import_references_from_text",
               AsyncMock(side_effect=ValueError("bad ref"))):
        with pytest.raises(HTTPException) as exc:
            await api.import_references(
                api.ImportReferencesBody(ref_text=""), db=MagicMock(),
                current_user=admin,
            )
    assert exc.value.status_code == 400


# ====== import_references_log ======

@pytest.mark.asyncio
async def test_import_references_log_records():
    user = User(id="00000000-0000-0000-0000-000000000002", username="normal",
                 hashed_password="x")
    with patch("app.api.v1.literature.import_export.create_import_log",
               AsyncMock()) as m_log:
        body = await api.import_references_log(
            api.ImportReferencesLogBody(file_name="x.ris", total_count=10,
                                         skipped_count=2, imported_count=8),
            db=MagicMock(), current_user=user,
        )
    m_log.assert_awaited_once()
    assert body.message == "导入日志已记录"


# ====== batch_import_from_folder ======

@pytest.mark.asyncio
async def test_batch_import_folder_success_builds_message():
    fake_result = {
        "matched": 1, "imported": 3, "skipped": 2, "failed": 0,
        "extraction_triggered": 2,
    }
    user = User(id="00000000-0000-0000-0000-000000000001", username="u",
                 hashed_password="x")
    with patch("app.api.v1.literature.import_export.batch_import_files_from_folder",
               AsyncMock(return_value=fake_result)):
        body = await api.batch_import_from_folder(
            folder_path="/data/pdfs", trigger_extraction_after=True,
            db=MagicMock(), current_user=user,
        )
    assert "关联 1 篇" in body.message
    assert "新建 3 篇" in body.message
    assert "跳过 2 篇" in body.message
    assert "已触发 2 篇 AI 提取" in body.message


@pytest.mark.asyncio
async def test_batch_import_folder_value_error_400():
    user = User(id="00000000-0000-0000-0000-000000000001", username="u",
                 hashed_password="x")
    with patch("app.api.v1.literature.import_export.batch_import_files_from_folder",
               AsyncMock(side_effect=ValueError("bad folder"))):
        with pytest.raises(HTTPException) as exc:
            await api.batch_import_from_folder(
                folder_path="/bad", trigger_extraction_after=True,
                db=MagicMock(), current_user=user,
            )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_batch_import_folder_file_not_found_400():
    user = User(id="00000000-0000-0000-0000-000000000001", username="u",
                 hashed_password="x")
    with patch("app.api.v1.literature.import_export.batch_import_files_from_folder",
               AsyncMock(side_effect=FileNotFoundError("no dir"))):
        with pytest.raises(HTTPException) as exc:
            await api.batch_import_from_folder(
                folder_path="/nonexist", trigger_extraction_after=True,
                db=MagicMock(), current_user=user,
            )
    assert exc.value.status_code == 400


# ====== batch_upload_files ======

@pytest.mark.asyncio
async def test_batch_upload_success_builds_message():
    fake_result = {
        "matched": 2, "imported": 5, "skipped": 1, "failed": 0,
        "extraction_triggered": 3,
    }
    user = User(id="00000000-0000-0000-0000-000000000001", username="u",
                 hashed_password="x")
    fake_files = [UploadFile(filename=f"f{i}.pdf", file=io.BytesIO(b"")) for i in range(3)]
    with patch("app.api.v1.literature.import_export.batch_import_uploaded_files",
               AsyncMock(return_value=fake_result)):
        body = await api.batch_upload_files(
            files=fake_files, trigger_extraction_after=True,
            db=MagicMock(), current_user=user,
        )
    assert "关联 2 篇" in body.message
    assert "新建 5 篇" in body.message
    assert "已触发 3 篇 AI 提取" in body.message


@pytest.mark.asyncio
async def test_batch_upload_value_error_400():
    user = User(id="00000000-0000-0000-0000-000000000001", username="u",
                 hashed_password="x")
    fake_files = [UploadFile(filename="a.pdf", file=io.BytesIO(b""))]
    with patch("app.api.v1.literature.import_export.batch_import_uploaded_files",
               AsyncMock(side_effect=ValueError("bad files"))):
        with pytest.raises(HTTPException) as exc:
            await api.batch_upload_files(
                files=fake_files, trigger_extraction_after=True,
                db=MagicMock(), current_user=user,
            )
    assert exc.value.status_code == 400
