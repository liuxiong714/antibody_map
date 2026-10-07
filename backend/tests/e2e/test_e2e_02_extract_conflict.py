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
        await db.commit()

        # 2. 造 ExtractionHistory（V7-03 新增 FK: extraction_history_id 必须存在）
        eh_id = str(uuid.uuid4())
        await db.execute(sa.text("""
            INSERT INTO extraction_history
            (id, literature_id, extracted_at, model, status,
             data_point_count, prompt_tokens, completion_tokens, total_tokens,
             llm_cost_usd, llm_call_count, duration_seconds, cache_hit)
            VALUES (:id, :lid, NOW(), 'e2e', 'success', 1, 10, 10, 20, 0, 1, 1, false)
        """), {"id": eh_id, "lid": lit_id})
        await db.commit()

        # 3. 造一个已有 DP（带 content_fingerprint）
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

        # 4. V5-01: 直接调生产函数 persist_data_points — 消除影子循环
        from app.tasks.extract_task import persist_data_points
        written, skipped = await persist_data_points(
            db, [conflict, new1, new2],
            history_model="e2e",
            history_id=eh_id,
        )
        await db.commit()

        # 5. 断言
        assert skipped == 1, f"应有 1 冲突被 skip, 实际 {skipped}"
        assert written == 2, f"应有 2 新点插入, 实际 {written}"

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
