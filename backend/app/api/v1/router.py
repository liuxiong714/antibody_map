from fastapi import APIRouter

from app.api.v1.dictionary import router as dictionary_router
from app.api.v1.extraction import router as extraction_router
from app.api.v1.literature import router as literature_router
from app.api.v1.map_data import router as map_router

router = APIRouter()

# 注册子路由
router.include_router(dictionary_router, tags=["dictionary"])
router.include_router(literature_router, tags=["literature"])
router.include_router(extraction_router, tags=["extraction"])
router.include_router(map_router, tags=["map"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "antibody-map-api", "version": "1.0.0"}
