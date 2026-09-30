"""snapshot_service.py 单元测试：分析请求可复现（快照 token + 数据指纹 + 引用文本）。

覆盖验收点：
- 同一查询两次调用 token 相同（同 module + 同 params + 同 data_hash 去重复用）
- 数据更新（value / review_status 变化）→ data_hash 变化 → 新 token
- data_hash 确定性：同集合同 hash；顺序无关（按 id 排序）
- build_citation 生成 gbt7714 / bibtex 引用文本（含版本号与访问日期）
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models.analysis_snapshot import AnalysisSnapshot
from app.services.snapshot_service import (
    calculate_data_hash,
    _upsert_snapshot,
    build_citation,
)


def point(dpid: str, review_status: str, value, **extra) -> SimpleNamespace:
    """构造一个哈希取数行（模拟 SQLAlchemy Row：id / review_status / value + 附加字段）。"""
    ns = SimpleNamespace(id=dpid, review_status=review_status, value=value)
    for k, v in extra.items():
        setattr(ns, k, v)
    return ns


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        class _Scalars:
            def __init__(self, rows):
                self._rows = rows

            def first(self):
                return self._rows[0] if self._rows else None

        return _Scalars(self._rows)


class FakeDB:
    """模拟 AsyncSession：对 AnalysisSnapshot 查询做简单过滤。"""

    def __init__(self, rows):
        self._rows = rows
        self.snapshots: list[AnalysisSnapshot] = []
        self.commits = 0

    async def execute(self, query):
        # 哈希取数查询（DataPoint）→ 返回行；快照去重查询（AnalysisSnapshot）→ 过滤快照
        desc = query.column_descriptions
        entity = desc[0]["entity"] if desc else None
        is_snapshot = entity is not None and entity.__name__ == "AnalysisSnapshot"
        if not is_snapshot:
            return FakeResult(self._rows)
        if query.whereclause is None:
            return FakeResult(self.snapshots)
        conditions = {}
        self._extract_conditions(query.whereclause, conditions)
        filtered = []
        for s in self.snapshots:
            match = True
            for key, val in conditions.items():
                if key == "module" and s.module != val:
                    match = False
                elif key == "data_hash" and s.data_hash != val:
                    match = False
            if match:
                filtered.append(s)
        return FakeResult(filtered)

    def _extract_conditions(self, node, out: dict):
        """递归提取 BinaryExpression 的键值对。"""
        from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList
        from sqlalchemy.sql.operators import eq
        if isinstance(node, BinaryExpression):
            left = str(node.left).split(".")[-1] if hasattr(node.left, "table") else str(node.left)
            if node.operator is eq:
                out[left] = node.right.value if hasattr(node.right, "value") else node.right
        elif isinstance(node, BooleanClauseList):
            for c in node.clauses:
                self._extract_conditions(c, out)

    def add(self, obj):
        # 模拟 SQLAlchemy flush 时应用 default=uuid.uuid4
        if obj.id is None:
            obj.id = uuid.uuid4()
        self.snapshots.append(obj)

    async def commit(self):
        self.commits += 1


# ── 1. data_hash 确定性 ───────────────────────────────────
def test_hash_deterministic_same_set():
    rows = [point("a", "approved", 25.0), point("b", "approved", 30.5)]
    assert calculate_data_hash(rows) == calculate_data_hash(rows)


def test_hash_order_independent():
    rows1 = [point("a", "approved", 25.0), point("b", "approved", 30.5)]
    rows2 = [point("b", "approved", 30.5), point("a", "approved", 25.0)]
    assert calculate_data_hash(rows1) == calculate_data_hash(rows2)


def test_hash_changes_on_value_change():
    before = calculate_data_hash([point("a", "approved", 25.0)])
    after = calculate_data_hash([point("a", "approved", 26.0)])
    assert before != after


def test_hash_changes_on_review_status_change():
    before = calculate_data_hash([point("a", "approved", 25.0)])
    after = calculate_data_hash([point("a", "pending", 25.0)])
    assert before != after


def test_hash_changes_on_sample_size_change():
    # F30：影响加权计算的字段（sample_size）变化也应触发新 hash
    before = calculate_data_hash([point("a", "approved", 25.0, sample_size=100)])
    after = calculate_data_hash([point("a", "approved", 25.0, sample_size=500)])
    assert before != after


def test_hash_changes_on_grouping_field_change():
    # F30：分组字段（province）变化也应触发新 hash
    before = calculate_data_hash([point("a", "approved", 25.0, province="北京")])
    after = calculate_data_hash([point("a", "approved", 25.0, province="广东")])
    assert before != after


def test_hash_16_hex_chars():
    h = calculate_data_hash([point("a", "approved", 25.0)])
    assert len(h) == 16
    int(h, 16)  # 必须是合法十六进制


# ── 2. 快照去重复用（同一查询两次调用 token 相同） ─────────────
async def _attach(db, module, params):
    data_hash = calculate_data_hash(db._rows)
    return await _upsert_snapshot(db, module, params, data_hash, {"ok": 1})


def test_same_query_same_token():
    import asyncio

    async def main():
        db = FakeDB([point("a", "approved", 25.0), point("b", "approved", 30.5)])
        params = {"disease": "measles", "province": "浙江"}
        t1 = await _attach(db, "trend", params)
        t2 = await _attach(db, "trend", params)
        assert t1 == t2, "同一查询两次调用 token 应相同"
        assert len(db.snapshots) == 1, "去重后只应写入一条快照"

    asyncio.run(main())


def test_data_change_gives_new_token():
    import asyncio

    async def main():
        # 第一次：value=25.0
        db1 = FakeDB([point("a", "approved", 25.0)])
        params = {"disease": "measles"}
        t1 = await _attach(db1, "trend", params)

        # 数据更新：value=26.0 → hash 变化
        db2 = FakeDB([point("a", "approved", 26.0)])
        t2 = await _attach(db2, "trend", params)

        assert t1 != t2, "数据更新后应产生新 token"

    asyncio.run(main())


def test_different_module_new_token():
    import asyncio

    async def main():
        db = FakeDB([point("a", "approved", 25.0)])
        t1 = await _attach(db, "trend", {"disease": "measles"})
        t2 = await _attach(db, "foi", {"disease": "measles"})
        assert t1 != t2

    asyncio.run(main())


# ── 3. 引用文本 ───────────────────────────────────────────
def _snap() -> AnalysisSnapshot:
    return AnalysisSnapshot(
        id="12345678-1234-5678-1234-567812345678",
        module="trend",
        params={"disease": "measles"},
        data_hash="a" * 16,
        response_json={"ok": 1},
    )


def test_citation_gbt7714():
    snap = _snap()
    text = build_citation(snap, style="gbt7714", accessed_date="2026-08-16")
    assert "[EB/OL]" in text
    assert "v1.0" in text  # 版本号
    assert "2026-08-16" in text  # 访问日期
    assert "12345678-1234-5678-1234-567812345678" in text  # 快照号
    assert "趋势" in text  # 模块中文名


def test_citation_bibtex():
    snap = _snap()
    text = build_citation(snap, style="bibtex", accessed_date="2026-08-16")
    assert text.startswith("@misc{")
    assert "antibodymap_snapshot_" in text
    assert "快照号" in text
    assert "访问日期" in text
    assert "2026-08-16" in text


def test_citation_default_style_is_gbt7714():
    snap = _snap()
    text = build_citation(snap)
    assert "[EB/OL]" in text
