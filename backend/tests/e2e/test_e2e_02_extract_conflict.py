"""E2E-2: 提取落库全链路（含冲突分支）"""
from __future__ import annotations
import uuid, pytest, sqlalchemy as sa
from tests.e2e.common import e2e_engine_session
from sqlalchemy.exc import IntegrityError as _IE

pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_extract_with_conflict_resolved():
    async with e2e_engine_session() as (engine, db):
        from app.models.data_point import DataPoint
        from app.models.literature import Literature
        from app.tasks.extract_task import _compute_dp_fingerprint

        # 1. 造文献
        lit_id = uuid.uuid4().hex
        await db.execute(sa.insert(Literature).values(
            id=lit_id, title="E2E-2", authors="test", journal="E2E", pub_year=2023,
            doi="10.0000/e2e2", abstract="abstract", pmid="00000001"
        ))

        # 2. 造一个已有 DP（带 content_fingerprint）
        existing = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="measles", province="北京", city="朝阳",
            data_type="seroprevalence", value=0.42, collection_year=2023,
            age_min=1, age_max=10, confidence="high", review_status="approved",
            estimate_type="primary", source_page=1, source_context="existing",
            is_grounded=True, model_used="e2e",
        )
        existing.content_fingerprint = _compute_dp_fingerprint(existing)
        db.add(existing)
        await db.commit()

        # 3. 造 3 个新 DP — conflict 与 existing 完全相同字段（+相同 FP）
        conflict = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="measles", province="北京", city="朝阳",
            data_type="seroprevalence", value=0.42, collection_year=2023,
            age_min=1, age_max=10, confidence="high", review_status="pending",
            estimate_type="primary", source_page=1, source_context="conflict",
            is_grounded=True, model_used="e2e",
        )
        conflict.content_fingerprint = existing.content_fingerprint  # 直接设成相同 FP

        new1 = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="rubella", province="上海", city="浦东",
            data_type="seroprevalence", value=0.35, collection_year=2023,
            age_min=2, age_max=8, confidence="high", review_status="pending",
            estimate_type="primary", source_page=1, source_context="new1",
            is_grounded=True, model_used="e2e",
        )
        new1.content_fingerprint = _compute_dp_fingerprint(new1)

        new2 = DataPoint(
            id=uuid.uuid4(), literature_id=lit_id,
            disease="mumps", province="广州", city="天河",
            data_type="seroprevalence", value=0.28, collection_year=2023,
            age_min=3, age_max=12, confidence="medium", review_status="pending",
            estimate_type="primary", source_page=1, source_context="new2",
            is_grounded=True, model_used="e2e",
        )
        new2.content_fingerprint = _compute_dp_fingerprint(new2)

        # 4. begin_nested 写库循环（V4-02 核心场景）
        inserted = []; skipped = 0
        for dp in [conflict, new1, new2]:
            async with db.begin_nested():
                try:
                    db.add(dp)
                    await db.flush()
                    inserted.append(dp)
                except _IE:
                    skipped += 1
                    continue  # V4-02: 这里不应再 rollback
        await db.commit()

        # 5. 断言
        assert skipped == 1, f"应有 1 冲突被 skip, 实际 {skipped}"
        assert len(inserted) == 2, f"应有 2 新点插入, 实际 {len(inserted)}"

        # 6. 最终行数: 1 existing + 2 new = 3
        cnt = (await db.execute(sa.text(
            "SELECT COUNT(*) FROM data_point WHERE literature_id = :lid"
        ), {"lid": lit_id})).scalar()
        assert cnt == 3

        # 7. grounding_rate
        total = cnt
        grounded = (await db.execute(sa.text(
            "SELECT COUNT(*) FROM data_point WHERE literature_id = :lid AND is_grounded = true"
        ), {"lid": lit_id})).scalar()
        assert 0 <= grounded / total <= 1.0
