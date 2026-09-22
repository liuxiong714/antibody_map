"""Phase 0: 多域数据扩展 —— data_point + literature 新增字段

从"血清抗体单域"扩展到"免疫—流行—病原"三域联动的第一步：
纯数据模型加法，不触碰任何现有字段和数据。

data_point 新增：
  - data_domain (VARCHAR DEFAULT 'immunology') — 数据域顶层分类
  - indicator (VARCHAR nullable) — 具体指标名
  - numerator / denominator (NUMERIC nullable) — 分子分母
  - period_type (VARCHAR DEFAULT 'year') — 时间粒度
  - period_month (INTEGER nullable) — 月份 1-12
  - pathogen / serotype / genotype / lineage / typing_method / specimen_type
  - extra (JSONB DEFAULT '{}') — 非常规维度兜底
  - 扩展 data_type CheckConstraint：新增 proportion/resistance_rate/positive_rate
    /attack_rate/secondary_attack_rate

literature 新增：
  - literature_type (VARCHAR nullable) — 文献类型标签
  - data_domain_tags (TEXT[] nullable) — 数据域多选标签

Down_revision 为二元组：merge migration 接两个已应用的 head。

Revision ID: add_multidomain_extension
Revises: add_datapoint_extraction_provenance, add_pathogen_monitoring
Create Date: 2026-09-20

幂等性：所有 ADD COLUMN 都用 IF NOT EXISTS，索引用 CREATE INDEX IF NOT EXISTS，
约束重建先检查存在性再 drop/create，避免已手动应用部分变更时报错。
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "add_multidomain_extension"
# Merge: 两条已应用的分支
down_revision = ("add_datapoint_extraction_provenance", "add_pathogen_monitoring")
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c)"
        ),
        {"t": table, "c": column},
    )
    return bool(result.scalar())


def _index_exists(index: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :n)"),
        {"n": index},
    )
    return bool(result.scalar())


def _constraint_exists(table: str, constraint: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_constraint c JOIN pg_class t ON c.conrelid = t.oid "
            "WHERE t.relname = :t AND c.conname = :c)"
        ),
        {"t": table, "c": constraint},
    )
    return bool(result.scalar())


def upgrade() -> None:
    # ===== data_point 新增字段（全部 IF NOT EXISTS）=====
    conn = op.get_bind()

    # data_point 列
    col_adds = [
        ("data_point", "data_domain", "VARCHAR(20) NOT NULL DEFAULT 'immunology'"),
        ("data_point", "indicator", "VARCHAR(50)"),
        ("data_point", "numerator", "NUMERIC(14,4)"),
        ("data_point", "denominator", "NUMERIC(14,4)"),
        ("data_point", "period_type", "VARCHAR(20) NOT NULL DEFAULT 'year'"),
        ("data_point", "period_month", "INTEGER"),
        ("data_point", "pathogen", "VARCHAR(200)"),
        ("data_point", "serotype", "VARCHAR(50)"),
        ("data_point", "genotype", "VARCHAR(50)"),
        ("data_point", "lineage", "VARCHAR(50)"),
        ("data_point", "typing_method", "VARCHAR(100)"),
        ("data_point", "specimen_type", "VARCHAR(100)"),
        ("data_point", "extra", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
        # literature 列
        ("literature", "literature_type", "VARCHAR(50)"),
        ("literature", "data_domain_tags", "TEXT[]"),
    ]
    for tbl, col, defn in col_adds:
        if not _col_exists(tbl, col):
            op.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {defn}")

    # ===== 新增索引（全部 IF NOT EXISTS）=====
    indexes = [
        ("ix_dp_data_domain", "CREATE INDEX ix_dp_data_domain ON data_point (data_domain)"),
        ("ix_dp_indicator", "CREATE INDEX ix_dp_indicator ON data_point (indicator)"),
        ("ix_dp_pathogen", "CREATE INDEX ix_dp_pathogen ON data_point (pathogen)"),
        ("ix_dp_genotype_new", "CREATE INDEX ix_dp_genotype_new ON data_point (genotype)"),
        ("ix_lit_literature_type", "CREATE INDEX ix_lit_literature_type ON literature (literature_type)"),
    ]
    for iname, stmt in indexes:
        if not _index_exists(iname):
            op.execute(stmt)

    # ===== 扩展 data_type CheckConstraint =====
    # 先 drop 旧约束，再创建新约束；若约束已更新过（新版本含 proportion 等），跳过
    new_check = (
        "data_type IN ("
        "'seroprevalence','gmc','incidence','case_count','mortality','death_count',"
        "'proportion','resistance_rate','positive_rate','attack_rate','secondary_attack_rate'"
        ")"
    )
    old_check = (
        "data_type IN ('seroprevalence','gmc','incidence','case_count','mortality','death_count')"
    )
    if _constraint_exists("data_point", "dp_data_type_check"):
        # 读当前约束表达式，判断是否已升级
        row = conn.execute(
            sa.text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "WHERE t.relname = 'data_point' AND c.conname = 'dp_data_type_check'"
            )
        ).fetchone()
        current_def = row[0] if row else ""
        if "proportion" not in current_def:
            op.drop_constraint("dp_data_type_check", "data_point", type_="check")
            op.create_check_constraint(
                "dp_data_type_check", "data_point", new_check,
            )
    else:
        op.create_check_constraint("dp_data_type_check", "data_point", new_check)


def downgrade() -> None:
    # ===== literature 回退 =====
    if _index_exists("ix_lit_literature_type"):
        op.drop_index("ix_lit_literature_type", table_name="literature")
    if _col_exists("literature", "data_domain_tags"):
        op.drop_column("literature", "data_domain_tags")
    if _col_exists("literature", "literature_type"):
        op.drop_column("literature", "literature_type")

    # ===== data_point CheckConstraint 回退 =====
    new_check = (
        "data_type IN ("
        "'seroprevalence','gmc','incidence','case_count','mortality','death_count',"
        "'proportion','resistance_rate','positive_rate','attack_rate','secondary_attack_rate'"
        ")"
    )
    old_check = (
        "data_type IN ('seroprevalence','gmc','incidence','case_count','mortality','death_count')"
    )
    if _constraint_exists("data_point", "dp_data_type_check"):
        row = op.get_bind().execute(
            sa.text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "WHERE t.relname = 'data_point' AND c.conname = 'dp_data_type_check'"
            )
        ).fetchone()
        current_def = row[0] if row else ""
        if "proportion" in current_def:
            op.drop_constraint("dp_data_type_check", "data_point", type_="check")
            op.create_check_constraint("dp_data_type_check", "data_point", old_check)

    # ===== data_point 索引回退 =====
    for idx in ["ix_dp_genotype_new", "ix_dp_pathogen", "ix_dp_indicator", "ix_dp_data_domain"]:
        if _index_exists(idx):
            op.drop_index(idx, table_name="data_point")

    # ===== data_point 字段回退 =====
    for col in [
        "extra", "specimen_type", "typing_method", "lineage", "genotype",
        "serotype", "pathogen", "period_month", "period_type",
        "denominator", "numerator", "indicator", "data_domain",
    ]:
        if _col_exists("data_point", col):
            op.drop_column("data_point", col)
