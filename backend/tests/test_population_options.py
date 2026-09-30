"""动态人群（职业）选项测试

测试目标：
1. service 函数正确拆分分号分隔的 population 值
2. 去重逻辑
3. 排序
4. 空值过滤
5. 按疾病筛选
6. API 端点注册
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.map_service import get_population_options


class FakeScalar:
    """模拟 SQLAlchemy 查询的标量结果"""
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self  # 返回自身，让 .all() 可调用

    def all(self):
        return self._values


class FakeDB:
    """模拟 AsyncSession"""
    def __init__(self, population_values):
        self._population_values = population_values
        self.executed_query = None

    async def execute(self, query):
        self.executed_query = query
        return FakeScalar(self._population_values)


# ── 测试 1: 基础拆分 ───────────────────────────────────
def test_basic_split():
    """population 字段包含分号分隔的多个值时正确拆分"""
    db = FakeDB(["健康人群", "医疗从业人员", "儿童;学生", "孕妇"])
    import asyncio
    result = asyncio.run(get_population_options(db))

    assert "健康人群" in result
    assert "医疗从业人员" in result
    assert "儿童" in result
    assert "学生" in result
    assert "孕妇" in result
    print("✓ test_basic_split")


# ── 测试 2: 去重 ───────────────────────────────────────
def test_deduplication():
    """重复的 population 值被去重"""
    db = FakeDB(["儿童", "儿童", "学生", "儿童;学生", "学生"])
    import asyncio
    result = asyncio.run(get_population_options(db))

    assert result.count("儿童") == 1
    assert result.count("学生") == 1
    print("✓ test_deduplication")


# ── 测试 3: 中文分号兼容 ───────────────────────────────
def test_chinese_semicolon():
    """中文分号（；）也能正确拆分"""
    db = FakeDB(["健康人群；医疗从业人员", "儿童；学生"])
    import asyncio
    result = asyncio.run(get_population_options(db))

    assert "健康人群" in result
    assert "医疗从业人员" in result
    assert "儿童" in result
    assert "学生" in result
    print("✓ test_chinese_semicolon")


# ── 测试 4: 空值过滤 ───────────────────────────────────
def test_empty_values_filtered():
    """空字符串和纯空白值被过滤"""
    db = FakeDB(["", "  ", "健康人群", ";", "；", "儿童;"])
    import asyncio
    result = asyncio.run(get_population_options(db))

    assert "" not in result
    assert "  " not in result
    assert "健康人群" in result
    assert "儿童" in result
    print("✓ test_empty_values_filtered")


# ── 测试 5: 排序 ───────────────────────────────────────
def test_sorted():
    """结果按字符排序"""
    db = FakeDB(["军人", "儿童", "老年人", "学生"])
    import asyncio
    result = asyncio.run(get_population_options(db))

    # 应该是排序后的
    assert result == sorted(result)
    print("✓ test_sorted")


# ── 测试 6: 空数据库 ───────────────────────────────────
def test_empty_database():
    """无数据时返回空列表"""
    db = FakeDB([])
    import asyncio
    result = asyncio.run(get_population_options(db))

    assert result == []
    print("✓ test_empty_database")


# ── 测试 7: 带空白的值被 strip ──────────────────────────
def test_whitespace_stripped():
    """值两端的空白被去除"""
    db = FakeDB(["  健康人群  ", "儿童 ; 学生"])
    import asyncio
    result = asyncio.run(get_population_options(db))

    assert "健康人群" in result
    assert "儿童" in result
    assert "学生" in result
    # 不应包含带空白的版本
    assert "  健康人群  " not in result
    assert " 儿童 " not in result
    print("✓ test_whitespace_stripped")


# ── 测试 8: API 端点注册 ───────────────────────────────
def test_api_endpoint_registered():
    """/map/population-options 端点已注册"""
    from app.api.v1.map_data import router
    paths = [r.path for r in router.routes]
    assert "/map/population-options" in paths
    print("✓ test_api_endpoint_registered")


# ── 测试 9: service 函数签名 ───────────────────────────
def test_service_signature():
    """get_population_options 接受 disease 参数"""
    import inspect
    sig = inspect.signature(get_population_options)
    assert "disease" in sig.parameters
    assert "db" in sig.parameters
    print("✓ test_service_signature")


# ── 测试 10: 前端 service 函数存在 ─────────────────────
def test_frontend_service_exists():
    """前端 map.ts 中有 getPopulationOptions 函数"""
    frontend_map = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "services" / "map.ts"
    content = frontend_map.read_text(encoding="utf-8")
    assert "getPopulationOptions" in content
    assert "/map/population-options" in content
    print("✓ test_frontend_service_exists")


# ── 测试 11: 前端组件使用动态选项 ──────────────────────
def test_frontend_uses_dynamic_options():
    """MapOverview.tsx 使用动态 populationOptions 而非硬编码"""
    component = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "pages" / "MapOverview.tsx"
    content = component.read_text(encoding="utf-8")
    assert "populationOptions" in content
    assert "getPopulationOptions" in content
    # 不再导入硬编码的 OCCUPATION_OPTIONS
    assert "OCCUPATION_OPTIONS" not in content
    print("✓ test_frontend_uses_dynamic_options")


# ── 测试 12: 疾病切换时重新获取 ────────────────────────
def test_refetch_on_disease_change():
    """疾病切换时 useEffect 重新获取人群选项"""
    component = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "pages" / "MapOverview.tsx"
    content = component.read_text(encoding="utf-8")
    # useEffect 依赖 disease
    assert "}, [disease]);" in content
    assert "getPopulationOptions(disease" in content
    print("✓ test_refetch_on_disease_change")


def run_all():
    tests = [
        test_basic_split,
        test_deduplication,
        test_chinese_semicolon,
        test_empty_values_filtered,
        test_sorted,
        test_empty_database,
        test_whitespace_stripped,
        test_api_endpoint_registered,
        test_service_signature,
        test_frontend_service_exists,
        test_frontend_uses_dynamic_options,
        test_refetch_on_disease_change,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: 异常 {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"动态人群选项测试: {passed}/{len(tests)} 通过, {failed} 失败")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
