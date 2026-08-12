from fastapi import APIRouter

from app.api.v1.dictionary import router as dictionary_router
from app.api.v1.extraction import router as extraction_router
from app.api.v1.literature import router as literature_router
from app.api.v1.map_data import router as map_router
from app.api.v1.search import router as search_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.report import router as report_router
from app.api.v1.folder_monitor import router as folder_monitor_router

router = APIRouter()

# 注册子路由
router.include_router(dictionary_router, tags=["dictionary"])
router.include_router(literature_router, tags=["literature"])
router.include_router(extraction_router, tags=["extraction"])
router.include_router(map_router, tags=["map"])
router.include_router(search_router, tags=["search"])
router.include_router(analysis_router, tags=["analysis"])
router.include_router(report_router, tags=["report"])
router.include_router(folder_monitor_router, tags=["folder_monitor"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "antibody-map-api", "version": "1.0.0"}
