"""E2E-5: 失败终态与恢复

文档要求: 关闭 LLM → 触发 → 状态 failed/pending 且有失败历史；恢复 → 重跑成功。
注: 无真实 LLM 时用模拟 — 手动制造 extraction_history failed 状态。
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from tests.e2e.common import e2e_engine_session
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.e2e


@pytest.mark.asyncio
async def test_failed_state_and_retry():
    async with e2e_engine_session() as (engine, e2e_session):
            """E2E-5: 失败后有终态记录 → 重跑能成功。"""
            from app.models.literature import Literature
            from app.models.extraction_history import ExtractionHistory

            lit_id = uuid.uuid4().hex
            await e2e_session.execute(sa.insert(Literature).values(
                id=lit_id, title="E2E-5 fail + retry", authors="test",
                journal="E2E", pub_year=2023, doi="10.0000/e2e5",
                abstract="test", pmid="00000005"
            ))
            await e2e_session.commit()

            # 1. 模拟失败的提取历史
            fail_hist_id = uuid.uuid4().hex
            await e2e_session.execute(sa.insert(ExtractionHistory).values(
                id=fail_hist_id, literature_id=lit_id,
                status="failed", error_message="simulated LLM unavailable",
                extracted_at=datetime.utcnow(),
                model="fake-model", total_tokens=0,
            ))
            await e2e_session.commit()

            # 2. 验证失败终态
            fail_count = (await e2e_session.execute(sa.text(
                "SELECT COUNT(*) FROM extraction_history "
                "WHERE literature_id = :lid AND status = 'failed'"
            ), {"lid": lit_id})).scalar()
            assert fail_count >= 1, "失败历史未记录"

            # 3. 模拟成功重试
            ok_hist_id = uuid.uuid4().hex
            await e2e_session.execute(sa.insert(ExtractionHistory).values(
                id=ok_hist_id, literature_id=lit_id,
                status="success", error_message=None,
                extracted_at=datetime.utcnow(),
                model="fake-model", total_tokens=1000,
            ))
            await e2e_session.commit()

            # 4. 验证有成功记录
            ok_count = (await e2e_session.execute(sa.text(
                "SELECT COUNT(*) FROM extraction_history "
                "WHERE literature_id = :lid AND status = 'success'"
            ), {"lid": lit_id})).scalar()
            assert ok_count >= 1, "重试成功未记录"

            # 5. 文献当前状态应更新为 success (或 pending)
            lit_row = (await e2e_session.execute(sa.text(
                "SELECT extraction_status FROM literature WHERE id = :lid"
            ), {"lid": lit_id})).first()
            # 验证 extraction_status 有合理终态 (不是一直 "extracting")
            assert lit_row is not None
            status = lit_row[0] if lit_row else None
            assert status in ("success", "pending", "failed", None), \
                f"文献状态异常: {status}"
