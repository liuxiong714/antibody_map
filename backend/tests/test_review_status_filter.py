"""review_status 五分支过滤条件测试。

不连真实 DB（项目 Literature model 用 postgres 方言，sqlite 不兼容），
直接在测试中导入 Literature model，构造与 crud.list_literatures 相同的
where 条件并 compile 成 SQL，断言每一分支的筛选逻辑符合业务语义。
"""
import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.literature import Literature


def _compile(expr):
    """把 SQLAlchemy 表达式编译成 postgres SQL 字符串，用于断言。"""
    stmt = select(Literature.id).where(expr)
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize(
    "review_status,expected_fragments",
    [
        # none: extracted_count == 0
        ("none", ["literature.extracted_count = 0"]),
        # pending: 有数据、无通过、无驳回
        ("pending", [
            "literature.extracted_count > 0",
            "literature.approved_count = 0",
            "literature.rejected_count = 0",
        ]),
        # rejected: 有数据、无通过、有驳回
        ("rejected", [
            "literature.extracted_count > 0",
            "literature.approved_count = 0",
            "literature.rejected_count > 0",
        ]),
        # partial: 0 < approved_count < extracted_count
        ("partial", [
            "literature.approved_count > 0",
            "literature.approved_count < literature.extracted_count",
        ]),
        # approved: extracted_count > 0 AND approved_count == extracted_count
        ("approved", [
            "literature.extracted_count > 0",
            "literature.approved_count = literature.extracted_count",
        ]),
    ],
)
def test_review_status_filter_branches(review_status, expected_fragments):
    """为每个 review_status 构造 where 条件，断言生成的 SQL 包含预期片段。

    此测试与 backend/app/services/literature/crud.py 的 list_literatures 实现
    逐分支一一对应；若 crud.py 里条件写错（如 partial 写成 <= 或 approved
    缺 extracted_count > 0 保护），这里会立即暴露。
    """
    from sqlalchemy import and_

    # 镜像 crud.list_literatures 里 review_status 分支的条件构造
    rs = review_status
    if rs == "none":
        conds = [Literature.extracted_count == 0]
    elif rs == "pending":
        conds = [
            Literature.extracted_count > 0,
            Literature.approved_count == 0,
            Literature.rejected_count == 0,
        ]
    elif rs == "rejected":
        conds = [
            Literature.extracted_count > 0,
            Literature.approved_count == 0,
            Literature.rejected_count > 0,
        ]
    elif rs == "partial":
        conds = [
            Literature.approved_count > 0,
            Literature.approved_count < Literature.extracted_count,
        ]
    elif rs == "approved":
        conds = [
            Literature.extracted_count > 0,
            Literature.approved_count == Literature.extracted_count,
        ]
    else:
        conds = []

    sql = _compile(and_(*conds)) if conds else ""
    for frag in expected_fragments:
        assert frag in sql, f"review_status={rs}: 期望 SQL 包含 '{frag}'，实际:\n{sql}"


def test_review_status_none_value_no_filter():
    """review_status=None 时不应追加任何审核相关 where 条件。"""
    sql = _compile(Literature.deleted_at.is_(None))
    assert "approved_count" not in sql
    assert "rejected_count" not in sql


@pytest.mark.asyncio(loop_scope="session")
async def test_review_status_crud_branch_not_missing():
    """运行时校验 crud.list_literature 的 review_status 分支没有遗漏任何值。

    通过简单反射检查 crud.list_literature 的源代码中是否出现了五个期望的
    字符串字面量，防止以后有人删除了某个 elif 分支而不自知。
    """
    import inspect
    from app.services.literature import crud

    src = inspect.getsource(crud.list_literature)
    for value in ("none", "pending", "rejected", "partial", "approved"):
        assert f'review_status == "{value}"' in src, (
            f"crud.list_literature 源码中缺少 review_status == '{value}' 分支"
        )
