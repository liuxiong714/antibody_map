from typing import Any, Optional

from pydantic import BaseModel, model_validator


class ApiResponse(BaseModel):
    success: bool = True
    message: str = "操作成功"
    data: Any = None
    meta: Optional[dict] = None


class PagedResponse(ApiResponse):
    """分页响应：统一继承 ApiResponse，返回结构为
    { success, message, data: { items, total, page, page_size }, meta }
    同时保留顶层 items/total/page/page_size 以兼容既有前端调用点。
    """

    items: list = []
    total: int = 0
    page: int = 1
    page_size: int = 20

    @model_validator(mode="after")
    def _fill_data(self) -> "PagedResponse":
        # 自动将分页数据注入 data 子对象，保证统一解包后仍可通过 resp.items 访问
        self.data = {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
        }
        return self
