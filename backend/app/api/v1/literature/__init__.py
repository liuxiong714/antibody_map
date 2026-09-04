"""文献模块路由 —— 聚合 CRUD、导入导出、文件操作、查重合并、孤儿清理 5 个子路由。"""

from fastapi import APIRouter

from .cleanup import router as cln_router
from .crud import router as crud_router
from .duplicates import router as dup_router
from .file import router as file_router
from .import_export import router as ie_router

router = APIRouter()

router.include_router(crud_router)
router.include_router(ie_router)
router.include_router(file_router)
router.include_router(dup_router)
router.include_router(cln_router)