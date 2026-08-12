"""BaseParser 基类及注册表。

所有格式解析器继承 BaseParser 并实现 extract() 方法。
通过 _PARSER_REGISTRY 自动注册，get_parser() 按扩展名查找。
"""
import io
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger("uvicorn")

# 全局解析器注册表：ext → parser_class
_PARSER_REGISTRY: dict[str, type["BaseParser"]] = {}


def register_parser(ext: str):
    """装饰器：将解析器类注册到全局注册表。"""
    def decorator(cls: type["BaseParser"]):
        ext_lower = ext.lower()
        if ext_lower in _PARSER_REGISTRY:
            logger.warning(f"解析器覆盖注册: {ext_lower} 原={_PARSER_REGISTRY[ext_lower].__name__} 新={cls.__name__}")
        _PARSER_REGISTRY[ext_lower] = cls
        return cls
    return decorator


def get_parser(file_ext: str) -> Optional["BaseParser"]:
    """按扩展名获取解析器实例（无状态，可复用）。"""
    cls = _PARSER_REGISTRY.get(file_ext.lower())
    if cls:
        return cls()
    logger.warning(f"[解析器注册表] 未找到 {file_ext} 的解析器，可用: {list(_PARSER_REGISTRY.keys())}")
    return None


def list_supported_exts() -> list[str]:
    """返回所有已注册的扩展名。"""
    return list(_PARSER_REGISTRY.keys())


class BaseParser(ABC):
    """解析器基类。子类必须定义 supported_ext 并实现 extract()。"""

    # 子类重写：此解析器支持的扩展名（带点，小写）
    supported_ext: str = ""

    @abstractmethod
    def extract(self, file_bytes: bytes) -> str:
        """从文件字节提取纯文本，返回空串表示解析失败。
        
        子类应自行捕获内部异常并返回空串，只有 RuntimeError 会被上抛。
        """
        ...

    def extract_text(self, file_bytes: bytes) -> str:
        """带日志的 extract 包装。"""
        parser_name = self.__class__.__name__
        try:
            result = self.extract(file_bytes)
            if result and result.strip():
                logger.info(f"[{parser_name}] 解析成功: {len(result)} 字符")
            else:
                logger.warning(f"[{parser_name}] 解析完成但文本为空 (可能为扫描件或空文件)")
            return result or ""
        except RuntimeError:
            logger.warning(f"[{parser_name}] extract 抛出 RuntimeError，向上传播")
            raise
        except Exception as e:
            logger.error(f"[{parser_name}] 解析异常: {e}")
            return ""