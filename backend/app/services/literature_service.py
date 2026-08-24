"""
文献服务兼容层。

v1.16.0 将原 literature_service.py 拆分为 backend/app/services/literature/ 包，
本文件保留所有公开符号的兼容引用，确保现有 API 调用不受影响。
"""
import logging

logger = logging.getLogger("uvicorn")

# ===== 从 _common 导入共享工具和常量 =====
from app.services.literature._common import (
    logger as _logger,
    LOCAL_STORAGE_DIR,
    _is_safe_local_path,
    compute_pdf_hash,
    normalize_title,
    _first_author_surname,
    _title_similarity,
    _is_dp_conflict,
    _dp_to_dict,
    FILE_FORMATS,
    _build_file_format_expr,
    TRASH_RETENTION_DAYS,
    _TITLE_EXT_PATTERN,
    _TITLE_YEAR_PREFIX,
    _TITLE_SUFFIX,
    _clean_filename_title,
    _read_literature_file_bytes,
    _find_existing_by_title,
    TRASH_CLEANUP_INTERVAL,
    _trash_cleanup_loop,
    create_import_log,
    list_import_logs,
)

# ===== 从 crud 导入基础 CRUD =====
from app.services.literature.crud import (
    list_literature,
    get_literature,
    create_literature,
    update_literature,
    delete_literature,
    get_file_history,
    log_file_action,
    get_literature_from_trash,
    list_trash_literatures,
    restore_literature,
    permanently_delete_literature,
    empty_trash,
    permanently_delete_all_trash,
)

# ===== 从 import_export 导入导入导出 =====
from app.services.literature.import_export import (
    upload_literature,
    _save_and_associate,
    upload_literature_file,
    preview_import_references,
    import_references_from_text,
    _BATCH_SUPPORTED_EXTS,
    _batch_import_files_core,
    batch_import_files_from_folder,
    batch_import_uploaded_files,
    import_literatures_from_json,
    build_literatures_export,
    reveal_in_host_file_manager,
    _to_windows_path,
    _get_wsl_runuser_prefix,
    _find_active_wsl_interop,
    stat_is_socket,
)

# ===== 从 cleanup 导入清理功能 =====
from app.services.literature.cleanup import (
    batch_delete_literatures,
    cleanup_empty_literatures,
)

# ===== 从 duplicates 导入查重合并 =====
from app.services.literature.duplicates import (
    check_duplicates,
    scan_duplicates,
    _MERGE_FIELDS,
    _ARRAY_FIELDS,
    preview_merge,
    merge_literatures,
)

# ===== 从 metadata 导入元数据同步 =====
from app.services.literature.metadata import (
    _TITLE_UNDERSCORE_TO_SLASH,
    _TITLE_AUTHOR_SUFFIX,
    _propose_title_fix,
    _TITLE_VERIFY_SYSTEM_PROMPT,
    _TITLE_VERIFY_USER_PROMPT,
    fix_titles,
    ai_verify_titles,
)

# 确保 logger 引用正确
logger = _logger

__all__ = [
    "LOCAL_STORAGE_DIR",
    "compute_pdf_hash",
    "normalize_title",
    "list_literature",
    "get_literature",
    "create_literature",
    "update_literature",
    "delete_literature",
    "upload_literature",
    "upload_literature_file",
    "get_file_history",
    "log_file_action",
    "check_duplicates",
    "scan_duplicates",
    "preview_merge",
    "merge_literatures",
    "batch_delete_literatures",
    "import_references_from_text",
    "preview_import_references",
    "cleanup_empty_literatures",
    "fix_titles",
    "ai_verify_titles",
    "batch_import_files_from_folder",
    "batch_import_uploaded_files",
    "import_literatures_from_json",
    "build_literatures_export",
    "reveal_in_host_file_manager",
    "list_trash_literatures",
    "restore_literature",
    "permanently_delete_literature",
    "empty_trash",
    "permanently_delete_all_trash",
    "create_import_log",
    "list_import_logs",
    "_trash_cleanup_loop",
    "_clean_filename_title",
    "_is_safe_local_path",
    "_find_existing_by_title",
    "_read_literature_file_bytes",
    "_propose_title_fix",
    "TRASH_RETENTION_DAYS",
    "TRASH_CLEANUP_INTERVAL",
    "FILE_FORMATS",
    "_build_file_format_expr",
    "_first_author_surname",
    "_title_similarity",
    "_is_dp_conflict",
    "_dp_to_dict",
    "_TITLE_EXT_PATTERN",
    "_TITLE_YEAR_PREFIX",
    "_TITLE_SUFFIX",
    "_TITLE_UNDERSCORE_TO_SLASH",
    "_TITLE_AUTHOR_SUFFIX",
    "_TITLE_VERIFY_SYSTEM_PROMPT",
    "_TITLE_VERIFY_USER_PROMPT",
    "_save_and_associate",
    "_BATCH_SUPPORTED_EXTS",
    "_batch_import_files_core",
    "_MERGE_FIELDS",
    "_ARRAY_FIELDS",
    "_to_windows_path",
    "_get_wsl_runuser_prefix",
    "_find_active_wsl_interop",
    "stat_is_socket",
]