"""时间序列化工具：统一将数据库返回的 UTC aware datetime 转为 Asia/Shanghai（北京时间）输出。

数据库所有 DateTime(timezone=True) 字段以 UTC 存储（默认 datetime.now(timezone.utc)）。
在序列化给前端时，应通过 iso_ts() 转成本地时区（Asia/Shanghai），保证展示时间与用户本地一致。
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# 应用展示时区：北京时间
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def iso_ts(dt: datetime | None) -> str | None:
    """将 aware datetime 转为 Asia/Shanghai 的 ISO 格式；naive 或 None 原样处理。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # naive 视为本地时间，直接序列化（无偏移）
        return dt.isoformat()
    # aware：统一转换为北京时间后输出
    return dt.astimezone(LOCAL_TZ).isoformat()