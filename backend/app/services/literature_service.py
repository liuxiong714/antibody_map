"""
文献服务兼容层。

v1.16.0 将原 literature_service.py 拆分为 backend/app/services/literature/ 包，
本文件保留所有公开符号的兼容引用，确保现有 API 调用不受影响。
"""
import logging

logger = logging.getLogger("uvicorn")

# ===== 从 _common 导入共享工具和常量 =====
from app.services.literature._common import (  # noqa: E402
    _TITLE_EXT_PATTERN,
    _TITLE_SUFFIX,
    _TITLE_YEAR_PREFIX,
    FILE_FORMATS,
    LOCAL_STORAGE_DIR,
    TRASH_CLEANUP_INTERVAL,
    TRASH_RETENTION_DAYS,
    _build_file_format_expr,
    _clean_filename_title,
    _dp_to_dict,
    _find_existing_by_title,
    _first_author_surname,
    _is_dp_conflict,
    _is_safe_local_path,
    _read_literature_file_bytes,
    _title_similarity,
    _trash_cleanup_loop,
    compute_pdf_hash,
    create_import_log,
    list_import_logs,
    normalize_title,
)
from app.services.literature._common import (  # noqa: E402
    logger as _logger,
)

# ===== 从 cleanup 导入清理功能 =====
from app.services.literature.cleanup import (  # noqa: E402
    batch_delete_literatures,
    cleanup_empty_literatures,
)

# ===== 从 crud 导入基础 CRUD =====
from app.services.literature.crud import (  # noqa: E402
    create_literature,
    delete_literature,
    empty_trash,
    get_file_history,
    get_literature,
    list_literature,
    list_trash_literatures,
    log_file_action,
    permanently_delete_all_trash,
    permanently_delete_literature,
    restore_literature,
    update_literature,
)

# ===== 从 duplicates 导入查重合并 =====
from app.services.literature.duplicates import (  # noqa: E402
    _ARRAY_FIELDS,
    _MERGE_FIELDS,
    check_duplicates,
    merge_literatures,
    preview_merge,
    scan_duplicates,
)

# ===== 从 import_export 导入导入导出 =====
from app.services.literature.import_export import (  # noqa: E402
    _BATCH_SUPPORTED_EXTS,
    _batch_import_files_core,
    _find_active_wsl_interop,
    _get_wsl_runuser_prefix,
    _save_and_associate,
    _to_windows_path,
    batch_import_files_from_folder,
    batch_import_uploaded_files,
    build_literatures_export,
    import_literatures_from_json,
    import_references_from_text,
    preview_import_references,
    reveal_in_host_file_manager,
    stat_is_socket,
    upload_literature,
    upload_literature_file,
)

# ===== 从 metadata 导入元数据同步 =====
from app.services.literature.metadata import (  # noqa: E402
    _TITLE_AUTHOR_SUFFIX,
    _TITLE_UNDERSCORE_TO_SLASH,
    _TITLE_VERIFY_SYSTEM_PROMPT,
    _TITLE_VERIFY_USER_PROMPT,
    _propose_title_fix,
    ai_verify_titles,
    fix_titles,
)

# 确保 logger 引用正确
logger = _logger

__all__ = [
    "FILE_FORMATS",
    "LOCAL_STORAGE_DIR",
    "TRASH_CLEANUP_INTERVAL",
    "TRASH_RETENTION_DAYS",
    "_ARRAY_FIELDS",
    "_BATCH_SUPPORTED_EXTS",
    "_MERGE_FIELDS",
    "_TITLE_AUTHOR_SUFFIX",
    "_TITLE_EXT_PATTERN",
    "_TITLE_SUFFIX",
    "_TITLE_UNDERSCORE_TO_SLASH",
    "_TITLE_VERIFY_SYSTEM_PROMPT",
    "_TITLE_VERIFY_USER_PROMPT",
    "_TITLE_YEAR_PREFIX",
    "_batch_import_files_core",
    "_build_file_format_expr",
    "_clean_filename_title",
    "_dp_to_dict",
    "_find_active_wsl_interop",
    "_find_existing_by_title",
    "_first_author_surname",
    "_get_wsl_runuser_prefix",
    "_is_dp_conflict",
    "_is_safe_local_path",
    "_propose_title_fix",
    "_read_literature_file_bytes",
    "_save_and_associate",
    "_title_similarity",
    "_to_windows_path",
    "_trash_cleanup_loop",
    "ai_verify_titles",
    "batch_delete_literatures",
    "batch_import_files_from_folder",
    "batch_import_uploaded_files",
    "build_literatures_export",
    "check_duplicates",
    "cleanup_empty_literatures",
    "compute_pdf_hash",
    "create_import_log",
    "create_literature",
    "delete_literature",
    "empty_trash",
    "fix_titles",
    "get_file_history",
    "get_literature",
    "import_literatures_from_json",
    "import_references_from_text",
    "list_import_logs",
    "list_literature",
    "list_trash_literatures",
    "log_file_action",
    "merge_literatures",
    "normalize_title",
    "permanently_delete_all_trash",
    "permanently_delete_literature",
    "preview_import_references",
    "preview_merge",
    "restore_literature",
    "reveal_in_host_file_manager",
    "scan_duplicates",
    "stat_is_socket",
    "update_literature",
    "upload_literature",
    "upload_literature_file",
]