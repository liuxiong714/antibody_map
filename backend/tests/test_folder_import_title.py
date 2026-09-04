"""测试文件夹监控导入文献标题修复：_clean_filename_title 路径净化、scan_folder 参数传递。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.services.literature_service import _clean_filename_title


class TestCleanFilenameTitle:
    """测试 _clean_filename_title 的路径净化功能"""

    def test_forward_slash_path_stripped(self):
        """ref/measles_2023.pdf → measles_2023"""
        result = _clean_filename_title("ref/measles_2023.pdf")
        assert result == "measles_2023"

    def test_backslash_path_stripped(self):
        """a\\b\\paper.docx → paper"""
        result = _clean_filename_title("a\\b\\paper.docx")
        assert result == "paper"

    def test_mixed_separator_path(self):
        """a/b\\c\\d/file.txt → file"""
        result = _clean_filename_title("a/b\\c\\d/file.txt")
        assert result == "file"

    def test_year_prefix_still_works(self):
        """2023_measles_survey.pdf → measles_survey（原有年份前缀清理不受影响）"""
        result = _clean_filename_title("2023_measles_survey.pdf")
        assert result == "measles_survey"

    def test_normal_title_unaffected(self):
        """seroprevalence study.pdf → seroprevalence study"""
        result = _clean_filename_title("seroprevalence study.pdf")
        assert result == "seroprevalence study"

    def test_path_with_year_prefix(self):
        """ref/2023_measles_survey.pdf → measles_survey（路径+年份复合）"""
        result = _clean_filename_title("ref/2023_measles_survey.pdf")
        assert result == "measles_survey"

    def test_path_without_extension(self):
        """ref/measles_2023 → measles_2023（无扩展名，路径净化后直接返回）"""
        result = _clean_filename_title("ref/measles_2023")
        assert result == "measles_2023"

    def test_normal_filename_without_path(self):
        """measles_2023.pdf → measles_2023"""
        result = _clean_filename_title("measles_2023.pdf")
        assert result == "measles_2023"

    def test_unknown_extension_preserved(self):
        """ref/file.tar.gz → file.tar.gz（.gz 不在扩展名列表中，路径净化后保留扩展名）"""
        result = _clean_filename_title("ref/file.tar.gz")
        # 路径被净化，但 .gz 不在 _TITLE_EXT_PATTERN 中，所以保留
        assert result == "file.tar.gz"

    def test_path_with_caj_extension(self):
        """监控/文献.caj → 文献"""
        result = _clean_filename_title("监控/文献.caj")
        assert result == "文献"

    def test_suffix_after_path(self):
        """ref/paper(1).pdf → paper（路径净化后序号后缀仍被清理）"""
        result = _clean_filename_title("ref/paper(1).pdf")
        assert result == "paper"

    def test_year_prefix_after_path(self):
        """ref/2023_副本_survey.docx → 副本_survey（路径净化后年份前缀仍被清理）"""
        result = _clean_filename_title("ref/2023_副本_survey.docx")
        assert result == "副本_survey"


class TestScanFolderTitleParameter:
    """验证 scan_folder 调用 upload_literature 时 title/filename 参数正确"""

    @pytest.mark.asyncio
    @patch("app.services.folder_monitor_service.upload_literature")
    @patch("app.services.folder_monitor_service.compute_pdf_hash")
    @patch("app.services.folder_monitor_service.trigger_extraction")
    async def test_scan_folder_passes_basename(
        self, mock_trigger, mock_hash, mock_upload
    ):
        """验证 scan_folder 传给 upload_literature 的 title 和 filename 不含路径前缀"""
        from app.services.folder_monitor_service import scan_folder

        # 准备 mock 的 upload_literature 返回值
        mock_lit = MagicMock()
        mock_lit.id = "test-uuid"
        mock_upload.return_value = (mock_lit, "new")
        mock_hash.return_value = "fakehash"

        # 准备 mock 的文件夹
        mock_folder = MagicMock()
        mock_folder.id = "folder-uuid"
        mock_folder.file_extensions = ".pdf"
        mock_folder.auto_extract = False
        mock_folder.status = "idle"
        mock_folder.name = "test-folder"
        mock_folder.total_imported_count = 0
        mock_folder.last_scan_new_count = 0

        # 创建临时目录和测试文件
        import tempfile
        tmpdir = tempfile.mkdtemp()
        test_file = Path(tmpdir) / "test_measles_2023.pdf"
        test_file.write_text("dummy content")
        mock_folder.folder_path = tmpdir

        mock_db = AsyncMock()
        # db.add 是同步方法，避免 AsyncMock 返回未 await 的协程告警
        mock_db.add = MagicMock(return_value=None)
        # 设置 db.execute 的 side_effect 依次返回 mock 结果（与 scan_folder 实际查询顺序一致）
        # 调用1: update(MonitoredFolder) 原子抢占扫描锁 → rowcount=1（抢占成功）
        # 调用2: select(MonitoredFile.file_path)... → r.all() 返回空列表
        # 调用3: select(Literature.id)... → scalar_one_or_none() 返回 None（无重复）
        mock_all = MagicMock(return_value=[])
        mock_scalar = MagicMock(return_value=None)
        mock_db.execute.side_effect = [
            MagicMock(rowcount=1),
            MagicMock(all=mock_all),
            MagicMock(scalar_one_or_none=mock_scalar),
        ]

        try:
            await scan_folder(mock_db, mock_folder)

            # 验证 upload_literature 被调用
            mock_upload.assert_called_once()
            call_args = mock_upload.call_args
            # args[0] = db, args[1] = file_bytes, args[2] = filename
            filename_arg = call_args[0][2]
            title_arg = call_args[1].get("title")
            assert filename_arg == "test_measles_2023.pdf", (
                f"filename 应为纯文件名, 实际: {filename_arg}"
            )
            assert title_arg == "test_measles_2023", (
                f"title 应为纯文件名 stem, 实际: {title_arg}"
            )
        finally:
            # 清理
            test_file.unlink()
            Path(tmpdir).rmdir()


class TestFixTitleFromCleanupScript:
    """验证清理脚本 _fix_title 函数的正确性"""

    def test_import_fix_title(self):
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title is not None

    def test_fix_title_forward_slash(self):
        """ref/measles_2023.pdf → measles_2023（有扩展名，修正）"""
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title("ref/measles_2023.pdf") == "measles_2023"

    def test_fix_title_backslash(self):
        """a\\b\\paper.docx → paper（有扩展名，修正）"""
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title("a\\b\\paper.docx") == "paper"

    def test_fix_title_no_extension_kept(self):
        """ref/measles_2023 → measles_2023（含下划线，视为文件名修正）"""
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title("ref/measles_2023") == "measles_2023"

    def test_fix_title_normal_title_unchanged(self):
        """正常含斜杠且无扩展名的标题不修改（如 and/or）"""
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title("and/or study") == "and/or study"

    def test_fix_title_html_extension(self):
        """webpage/result.html → result（有扩展名，修正）"""
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title("webpage/result.html") == "result"

    def test_fix_title_and_or_preserved(self):
        """and/or 等正常含斜杠标题不误伤（无扩展名、无中文、无下划线）"""
        from scripts.fix_folder_import_titles import _fix_title
        assert _fix_title("and/or") == "and/or"