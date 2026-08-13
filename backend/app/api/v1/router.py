from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1.auth import router as auth_router
from app.api.v1.dictionary import router as dictionary_router
from app.api.v1.extraction import router as extraction_router
from app.api.v1.literature import router as literature_router
from app.api.v1.map_data import router as map_router
from app.api.v1.search import router as search_router
from app.api.v1.analysis import router as analysis_router
from app.api.v1.report import router as report_router
from app.api.v1.folder_monitor import router as folder_monitor_router
from app.api.v1.model_config import router as model_config_router

router = APIRouter()

# ── 公开路由（无需认证）──
router.include_router(auth_router, tags=["auth"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "antibody-map-api", "version": "1.0.0"}


# ── 需要认证的路由（自动注入 get_current_user）──
_protected = APIRouter(dependencies=[Depends(get_current_user)])
_protected.include_router(dictionary_router, tags=["dictionary"])
_protected.include_router(literature_router, tags=["literature"])
_protected.include_router(extraction_router, tags=["extraction"])
_protected.include_router(map_router, tags=["map"])
_protected.include_router(search_router, tags=["search"])
_protected.include_router(analysis_router, tags=["analysis"])
_protected.include_router(report_router, tags=["report"])
_protected.include_router(folder_monitor_router, tags=["folder_monitor"])
_protected.include_router(model_config_router, tags=["models"])
router.include_router(_protected)
