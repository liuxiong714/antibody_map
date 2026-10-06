"""E2E-3: 重复触发幂等"""
from __future__ import annotations
import uuid, pytest, sqlalchemy as sa
from tests.e2e.common import e2e_engine_session
from app.tasks.extract_task import _compute_dp_fingerprint
from sqlalchemy.exc import IntegrityError as _IE

pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_idempotent_extract():
    async with e2e_engine_session() as (engine, db):
        from app.models.data_point import DataPoint
        from app.models.literature import Literature

        lit_id = uuid.uuid4().hex
        await db.execute(sa.insert(Literature).values(
            id=lit_id, title="E2E-3 idempotent", authors="test",
            journal="E2E", pub_year=2023, doi="10.0000/e2e3",
            abstract="test", pmid="00000003"
        ))

        # 1. 造 DP1 并设 FP
        dp1 = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="measles", province="北京", city="朝阳",
            data_type="seroprevalence", value=0.42, collection_year=2023,
            age_min=1, age_max=10, confidence="high", review_status="pending",
            estimate_type="primary", source_page=1, source_context="first",
            is_grounded=True, model_used="e2e",
        )
        dp1.content_fingerprint = _compute_dp_fingerprint(dp1)
        db.add(dp1)
        await db.commit()

        first_count = (await db.execute(sa.text(
            "SELECT COUNT(*) FROM data_point WHERE literature_id = :lid"
        ), {"lid": lit_id})).scalar()
        assert first_count == 1

        # 2. 模拟第二次触发 — 造同字段（同 FP）的 duplicate
        dup = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="measles", province="北京", city="朝阳",
            data_type="seroprevalence", value=0.42, collection_year=2023,
            age_min=1, age_max=10, confidence="high", review_status="pending",
            estimate_type="primary", source_page=1, source_context="dup",
            is_grounded=True, model_used="e2e",
        )
        dup.content_fingerprint = dp1.content_fingerprint  # 相同 FP → 应冲突

        async with db.begin_nested():
            try:
                db.add(dup); await db.flush()
                # 如果没抛异常，手动回滚并报错
                await db.rollback()
                raise AssertionError("重复 FP 应触发 IntegrityError")
            except AssertionError:
                raise
            except _IE:
                pass  # 期望

        await db.commit()

        # 3. 最终行数不变
        final = (await db.execute(sa.text(
            "SELECT COUNT(*) FROM data_point WHERE literature_id = :lid"
        ), {"lid": lit_id})).scalar()
        assert final == first_count, f"幂等失败: 初始 {first_count}, 最终 {final}"
