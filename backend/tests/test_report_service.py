"""report_service.generate_report 可复现性单元测试（F38）。

验证：
- 引用/编号中的日期全部取自同一次生成的 gen_date（一次性计算），不存在
  多处 date.today() 导致的跨日不一致；
- Report.generated_at 绑定该 gen_date，且为带时区的时间（UTC）；
- 报告正文中「数据截至」「引用日期」「报告编号」三处日期完全一致。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.report_service import generate_report


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self._rows = rows
        self.added = None

    async def execute(self, query):
        return FakeResult(self._rows)

    def add(self, obj):
        self.added = obj

    async def commit(self):
        pass


def _dp(lit_id, value, ss, province="广东", year=2022, age_min=None, age_max=None):
    return SimpleNamespace(
        literature_id=lit_id, value=value, sample_size=ss, province=province,
        collection_year=year, age_min=age_min, age_max=age_max,
        data_type="seroprevalence", review_status="approved",
    )


def asyncio_run(coro):
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import threading

    result = {}

    def _runner():
        result["v"] = asyncio.new_event_loop().run_until_complete(coro)

    t = threading.Thread(target=_runner)
    t.start()
    t.join()
    return result["v"]


class TestReportReproducibility:
    def _run_report(self):
        rows = [_dp(1, 15.0, 100, province="广东"), _dp(2, 30.0, 200, province="广东")]
        db = FakeDB(rows)
        with patch(
            "app.services.report_service.get_default_template",
            AsyncMock(return_value=None),
        ), patch(
            "app.services.report_service._call_llm",
            AsyncMock(return_value="## 正文\n测试生成内容。"),
        ):
            out = asyncio_run(generate_report(db=db, disease="measles", province="广东"))
        return out, db

    def test_citation_dates_all_consistent(self):
        # F38：引用小节的 数据截至 / 引用日期 / 报告编号 三处日期必须完全一致
        out, _ = self._run_report()
        content = out["content"]
        assert "## 引用" in content
        citation = content.split("## 引用", 1)[1]
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", citation)
        assert len(dates) == 3, f"引用应含 3 处日期，实际 {len(dates)}"
        assert len(set(dates)) == 1, f"引用日期不一致: {dates}"

    def test_generated_at_bound_and_timezone_aware(self):
        # F38：generated_at 绑定生成时间，带时区（UTC），且与引用日期同一天
        out, db = self._run_report()
        assert db.added is not None
        gen = db.added.generated_at
        assert gen is not None
        assert gen.tzinfo is not None, "generated_at 必须是带时区的时间"
        citation_date = re.findall(r"\d{4}-\d{2}-\d{2}", out["content"].split("## 引用", 1)[1])[0]
        assert gen.date().isoformat() == citation_date

    def test_report_id_uses_generation_date(self):
        # F38：报告编号形如 疾病_省份_YYYY-MM-DD，日期与生成时间一致
        out, _ = self._run_report()
        m = re.search(r"报告编号：(\S+)_(\S+)_(\d{4}-\d{2}-\d{2})", out["content"])
        assert m is not None
        assert m.group(1) == "麻疹"
        assert m.group(2) == "广东"
        citation_date = re.findall(r"\d{4}-\d{2}-\d{2}", out["content"].split("## 引用", 1)[1])[0]
        assert m.group(3) == citation_date
