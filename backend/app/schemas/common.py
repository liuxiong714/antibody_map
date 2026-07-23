from typing import Any, Optional

from pydantic import BaseModel


class ApiResponse(BaseModel):
    success: bool = True
    message: str = "操作成功"
    data: Any = None
    meta: Optional[dict] = None


class PagedResponse(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
