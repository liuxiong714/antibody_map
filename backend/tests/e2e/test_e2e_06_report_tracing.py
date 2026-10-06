"""E2E-6: 报告可信度 — 数值溯源"""
from __future__ import annotations
import uuid, pytest, sqlalchemy as sa
from tests.e2e.common import e2e_engine_session
from app.tasks.extract_task import _compute_dp_fingerprint
from app.services.report_service import _verify_report_tracing, _data_snapshot_hash

pytestmark = pytest.mark.e2e

@pytest.mark.asyncio
async def test_report_tracing_complete():
    async with e2e_engine_session() as (engine, db):
        from app.models.data_point import DataPoint
        from app.models.literature import Literature

        lit_id = uuid.uuid4().hex
        await db.execute(sa.insert(Literature).values(
            id=lit_id, title="E2E-6 report tracing", authors="test",
            journal="E2E", pub_year=2023, doi="10.0000/e2e6",
            abstract="test", pmid="00000006"
        ))

        # 造已审核数据点 — 给足 content_fingerprint + source_context
        dps = []
        for dis, prov, val in [("measles", "北京", 0.42), ("rubella", "上海", 0.35), ("mumps", "广州", 0.28)]:
            dp = DataPoint(
                id=uuid.uuid4(), literature_id=lit_id,
                disease=dis, province=prov, city="test",
                data_type="seroprevalence", value=val, collection_year=2023,
                age_min=1, age_max=10, confidence="high", review_status="approved",
                estimate_type="primary", source_page=1,
                source_context=f"原文提到 {val*100:.0f}% 阳性率 — E2E-6 测试",
                is_grounded=True, model_used="e2e",
            )
            dp.content_fingerprint = _compute_dp_fingerprint(dp)
            dps.append(dp)
            db.add(dp)
        await db.commit()

        # 关键: re-fetch 确保 ORM 对象已与 DB 同步
        from sqlalchemy import select
        result = await db.execute(
            select(DataPoint).where(DataPoint.literature_id == lit_id)
        )
        rows = result.scalars().all()
        assert len(rows) == 3, f"应取回 3 条, 实际 {len(rows)}"

        # 检查 source_context 实际有值
        for r in rows:
            ctx = r.source_context or ""
            assert len(ctx.strip()) >= 10, \
                f"source_context 太短: '{ctx}' (len={len(ctx.strip())})"

        # 跑溯源校验
        tracing = await _verify_report_tracing(rows)
        assert tracing["total"] == 3
        assert tracing["ungrounded"] == 0
        assert tracing["missing_context"] == 0, \
            f"missing_context={tracing['missing_context']}, 应有 0"

        # snapshot hash
        h = _data_snapshot_hash(rows)
        assert h and len(h) == 64

        # dict 输入也应正确（V3-10/V4-06 回归防护）
        dict_rows = [
            {"is_grounded": True, "source_context": "ok context text", "id": "d1"},
            {"is_grounded": True, "source_context": "ok context text", "id": "d2"},
        ]
        t2 = await _verify_report_tracing(dict_rows)
        assert t2["ungrounded"] == 0
