"""业务异常基类与常用异常定义。

全局异常处理器（见 ``app/main.py``）会将此类异常统一渲染为：

.. code-block:: json

    {
        "success": false,
        "code": "ERROR_CODE",
        "message": "人类可读消息",
        "data": null,
        "request_id": "可选"
    }
"""

from typing import Any


class AppError(Exception):
    """业务异常基类：携带可由异常处理器映射到响应的结构化信息。"""

    code: str
    status_code: int
    message: str
    details: Any

    def __init__(
        self,
        message: str = "处理失败",
        *,
        code: str = "APP_ERROR",
        status_code: int = 400,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class LLMExtractionError(AppError):
    """LLM 文献数据提取错误（模型调用 / 结构化字段解析失败）。"""

    def __init__(
        self,
        message: str = "LLM 提取失败",
        *,
        code: str = "LLM_EXTRACTION_ERROR",
        status_code: int = 500,
        details: Any = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class DocumentParseError(AppError):
    """文档解析错误（PDF/CAJ 等文件解析失败）。"""

    def __init__(
        self,
        message: str = "文档解析失败",
        *,
        code: str = "DOCUMENT_PARSE_ERROR",
        status_code: int = 422,
        details: Any = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)


class ExternalAPIError(AppError):
    """外部 API 调用错误（跨库 / 检索 / 第三方服务异常）。"""

    def __init__(
        self,
        message: str = "外部服务调用失败",
        *,
        code: str = "EXTERNAL_API_ERROR",
        status_code: int = 502,
        details: Any = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)