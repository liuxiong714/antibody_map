"""V4-02 行为级守护测试：SAVEPOINT + IntegrityError 分支 **不能** 再调 Session.rollback()

背景：V3-02 修复唯一约束冲突时，except 分支里多写了 `await db.rollback()` ——
begin_nested() 异常退出时 SQLAlchemy 已自动发 ROLLBACK TO SAVEPOINT，外层事务完好。
此时再调 Session.rollback() 会把外层事务里本批次此前已 flush 的数据点全部作废。
症状：冲突点之后的点保留，冲突点之前的点丢失。

本测试：真实 PostgreSQL + 真实唯一约束 + 真实 Session。
       预置冲突点 → 跑写库循环 → 断言冲突点前后的点都能保住。

反向验证（commit 前必须做一次）：
  临时把 extract_task.py 里删掉的 `await db.rollback()` 加回去 → 本测试应 **失败**
  再删掉 → 恢复通过（证明测试真能抓到 V4-02 这类语义错误）
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.literature import Literature
from app.models.extraction_history import ExtractionHistory
from app.models.data_point import DataPoint

pytestmark = pytest.mark.asyncio


def _mk_dp(literature_id, fingerprint_variant: str) -> DataPoint:
    """构造能通过 CheckConstraint + 参与指纹计算的 DataPoint。"""
    disease_map = {
        "batch_ahead":    "measles",
        "batch_conflict": "rubella",
        "batch_after":    "mumps",
        "existing":       "rubella",
    }
    dp = DataPoint(
        id=uuid.uuid4(),
        literature_id=literature_id,
        disease=disease_map[fingerprint_variant],
        province="北京",
        city="朝阳",
        data_type="seroprevalence",
        value=0.42,
        collection_year=2023,
        age_min=1,
        age_max=10,
        confidence="medium",
        review_status="pending",
        estimate_type="primary",
        source_page=1,
        source_context="test",
        is_grounded=True,
        model_used="test-model",
    )
    return dp


async def _write_batch_with_savepoint(db: AsyncSession, dps: list[DataPoint]) -> tuple[int, int]:
    """等价于 extract_task.py 的写库循环 —— V4-02 修复后版本（**无** Session.rollback()）。"""
    from app.tasks.extract_task import _compute_dp_fingerprint
    _skipped = 0
    _written = 0
    for dp in dps:
        dp.content_fingerprint = _compute_dp_fingerprint(dp)
        try:
            async with db.begin_nested():
                db.add(dp)
                await db.flush()
            _written += 1
        except IntegrityError:
            # begin_nested() 异常退出时 SQLAlchemy 已自动 ROLLBACK TO SAVEPOINT
            # V4-02: 此处**不再** await db.rollback()（Session 级回滚会把外层事务全部作废）
            _skipped += 1
            continue
    return _written, _skipped


class TestV402SavepointSemantics:
    """真 PG + 真唯一约束下，SAVEPOINT 冲突前后点都保住。"""

    async def test_conflict_isolation_preserves_neighbors(self):
        """预置 existing(fpA)，构造 batch=[dp1(fp1), dp2(fpA=冲突), dp3(fp3)]

        断言：dp1 和 dp3 都落库（_written=2），dp2 被跳过（_skipped=1）。
        """
        from app.tasks.extract_task import _compute_dp_fingerprint

        engine = create_async_engine(settings.DATABASE_URL)

        # 确保唯一索引存在（幂等）
        async with engine.begin() as conn:
            await conn.execute(sa.text("DROP INDEX IF EXISTS uq_dp_lit_fingerprint"))
            await conn.execute(sa.text(
                "CREATE UNIQUE INDEX uq_dp_lit_fingerprint "
                "ON data_point (literature_id, content_fingerprint) "
                "WHERE content_fingerprint IS NOT NULL "
                "AND content_fingerprint != '' "
                "AND review_status != 'rejected'"
            ))

        SL = async_sessionmaker(engine, expire_on_commit=False)

        async with SL() as db:
            try:
                # 1) 预置父记录
                lit = Literature(
                    id=uuid.uuid4(),
                    title="V4-02 测试文献",
                    pub_year=2023,
                    extraction_status="done",
                )
                hist = ExtractionHistory(
                    id=uuid.uuid4(),
                    literature_id=lit.id,
                    model="test-model",
                    status="success",
                    cache_hit=False,
                )
                db.add(lit); await db.flush()
                db.add(hist); await db.flush()

                # 2) 预置 1 条 existing DataPoint（fpA）
                existing = _mk_dp(lit.id, "existing")
                existing.content_fingerprint = _compute_dp_fingerprint(existing)
                db.add(existing)
                await db.commit()

                # 3) 构造批次 + 验证冲突设计
                dp1 = _mk_dp(lit.id, "batch_ahead")
                dp2 = _mk_dp(lit.id, "batch_conflict")
                dp3 = _mk_dp(lit.id, "batch_after")
                assert _compute_dp_fingerprint(dp2) == existing.content_fingerprint, \
                    "夹具错误: dp2 应与 existing 同 fingerprint"
                assert _compute_dp_fingerprint(dp1) != existing.content_fingerprint
                assert _compute_dp_fingerprint(dp3) != existing.content_fingerprint

                # 4) 跑修复后的写库循环
                written, skipped = await _write_batch_with_savepoint(db, [dp1, dp2, dp3])
                await db.commit()

                # 5) 关键断言
                assert skipped == 1, f"应跳过 1 条冲突，实际 skipped={skipped}"
                assert written == 2, f"应写入 2 条（dp1 + dp3），实际 written={written}"

                rows = (await db.execute(
                    sa.select(DataPoint).where(DataPoint.literature_id == lit.id)
                )).scalars().all()
                assert len(rows) == 3, f"库中应 3 条（existing/dp1/dp3），实际 {len(rows)}"

                row_fps = [r.content_fingerprint for r in rows]
                assert existing.content_fingerprint in row_fps
                assert _compute_dp_fingerprint(dp1) in row_fps, "dp1 丢失！（V4-02 症状：冲突前点被 Session.rollback 吃掉）"
                assert _compute_dp_fingerprint(dp3) in row_fps, "dp3 丢失！（V4-02 症状）"
                assert row_fps.count(existing.content_fingerprint) == 1, \
                    "dp2 应被唯一约束拦截 —— 但 fpA 在库里出现了不止一次"
            finally:
                await db.rollback()
        await engine.dispose()
