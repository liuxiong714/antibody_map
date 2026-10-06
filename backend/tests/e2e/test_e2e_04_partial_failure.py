"""E2E-4: 导入部分失败 — 用唯一约束而非 CheckConstraint（更可靠）"""
from __future__ import annotations
import uuid, pytest, sqlalchemy as sa
from tests.e2e.common import e2e_engine_session
from app.tasks.extract_task import _compute_dp_fingerprint
from sqlalchemy.exc import IntegrityError as _IE

pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_partial_import_failure():
    async with e2e_engine_session() as (engine, db):
        from app.models.data_point import DataPoint
        from app.models.literature import Literature

        lit_id = uuid.uuid4().hex
        await db.execute(sa.insert(Literature).values(
            id=lit_id, title="E2E-4 partial", authors="test",
            journal="E2E", pub_year=2023, doi="10.0000/e2e4",
            abstract="test", pmid="00000004"
        ))

        # 策略: 先插 ok2, 让 bad 跟 ok2 有相同 FP → bad 触发唯一约束
        ok1 = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="measles", province="北京", city="朝阳",
            data_type="seroprevalence", value=0.42, collection_year=2023,
            age_min=1, age_max=10, confidence="high", review_status="pending",
            estimate_type="primary", source_page=1, source_context="ok1",
            is_grounded=True, model_used="e2e",
        )
        ok1.content_fingerprint = _compute_dp_fingerprint(ok1)

        ok2 = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="rubella", province="上海", city="浦东",
            data_type="seroprevalence", value=0.35, collection_year=2023,
            age_min=2, age_max=8, confidence="high", review_status="pending",
            estimate_type="primary", source_page=1, source_context="ok2",
            is_grounded=True, model_used="e2e",
        )
        ok2.content_fingerprint = _compute_dp_fingerprint(ok2)

        # bad: content_fingerprint 故意设成和 ok2 一样 → 触发唯一约束
        bad = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="mumps", province="广州", city="天河",
            data_type="seroprevalence", value=0.28, collection_year=2023,
            age_min=3, age_max=12, confidence="medium", review_status="pending",
            estimate_type="primary", source_page=1, source_context="bad",
            is_grounded=True, model_used="e2e",
        )
        bad.content_fingerprint = ok2.content_fingerprint  # 跟 ok2 相同 → 冲突!

        imported = 0; failed = 0
        for dp in [ok1, bad, ok2]:
            async with db.begin_nested():
                try:
                    db.add(dp); await db.flush()
                    imported += 1
                except _IE:
                    failed += 1
                    continue
        await db.commit()

        assert imported == 2, f"应成功 2 条, 实际 {imported}"
        assert failed == 1, f"应有 1 条失败, 实际 {failed}"

        cnt = (await db.execute(sa.text(
            "SELECT COUNT(*) FROM data_point WHERE literature_id = :lid"
        ), {"lid": lit_id})).scalar()
        assert cnt == 2, f"库中应 2 条, 实际 {cnt}"
