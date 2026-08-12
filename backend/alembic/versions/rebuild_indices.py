"""rebuild_indices

重建 data_point 和 literature 表的核心索引：
- 恢复 init.py 中被误删除的 4 个单列索引
- 新增 estimate_type / data_type / literature_id 等单列索引
- 新增 2 个热门复合索引匹配最常用的 WHERE 组合
  (review_status, estimate_type, disease)  - 地图/分析/报告高频查询
  (disease, province, collection_year)      - 分省×年份钻取查询

Revision ID: rebuild_indices
Revises: encrypt_api_keys
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union
import logging

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'rebuild_indices'
down_revision: Union[str, Sequence[str], None] = 'encrypt_api_keys'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic")


def upgrade() -> None:
    # ---- data_point 单列索引（if_not_exists 避免重复） ----
    op.create_index(
        op.f('idx_dp_collection_year'), 'data_point', ['collection_year'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_dp_disease'), 'data_point', ['disease'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_dp_province'), 'data_point', ['province'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_dp_review_status'), 'data_point', ['review_status'],
        if_not_exists=True,
    )
    # 新增单列索引
    op.create_index(
        op.f('idx_dp_estimate_type'), 'data_point', ['estimate_type'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_dp_data_type'), 'data_point', ['data_type'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_dp_literature_id'), 'data_point', ['literature_id'],
        if_not_exists=True,
    )

    # ---- data_point 复合索引（匹配高频 WHERE 组合） ----
    # 最热门：review_status + estimate_type + disease
    #   地图/分析/报告几乎都用 WHERE review_status='approved' AND estimate_type='primary' AND disease=X
    op.create_index(
        op.f('idx_dp_comp_review_estimate_disease'),
        'data_point', ['review_status', 'estimate_type', 'disease'],
        if_not_exists=True,
    )
    # 次热门：disease + province + collection_year
    #   分省×年份钻取：WHERE disease=X AND province LIKE %Y% AND collection_year BETWEEN ...
    op.create_index(
        op.f('idx_dp_comp_disease_province_year'),
        'data_point', ['disease', 'province', 'collection_year'],
        if_not_exists=True,
    )

    # ---- literature 单列索引 ----
    op.create_index(
        op.f('idx_lit_extraction_status'), 'literature', ['extraction_status'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_lit_province'), 'literature', ['province'],
        if_not_exists=True,
    )
    op.create_index(
        op.f('idx_lit_pub_year'), 'literature', ['pub_year'],
        if_not_exists=True,
    )

    logger.info("索引重建完成：data_point 7 单列 + 2 复合，literature 3 单列")


def downgrade() -> None:
    # ---- 删除复合索引 ----
    op.drop_index(
        op.f('idx_dp_comp_disease_province_year'), table_name='data_point',
        if_exists=True,
    )
    op.drop_index(
        op.f('idx_dp_comp_review_estimate_disease'), table_name='data_point',
        if_exists=True,
    )

    # ---- 删除 data_point 单列索引 ----
    op.drop_index(op.f('idx_dp_literature_id'), table_name='data_point', if_exists=True)
    op.drop_index(op.f('idx_dp_data_type'), table_name='data_point', if_exists=True)
    op.drop_index(op.f('idx_dp_estimate_type'), table_name='data_point', if_exists=True)
    op.drop_index(op.f('idx_dp_review_status'), table_name='data_point', if_exists=True)
    op.drop_index(op.f('idx_dp_province'), table_name='data_point', if_exists=True)
    op.drop_index(op.f('idx_dp_disease'), table_name='data_point', if_exists=True)
    op.drop_index(op.f('idx_dp_collection_year'), table_name='data_point', if_exists=True)

    # ---- 删除 literature 单列索引 ----
    op.drop_index(op.f('idx_lit_pub_year'), table_name='literature', if_exists=True)
    op.drop_index(op.f('idx_lit_province'), table_name='literature', if_exists=True)
    op.drop_index(op.f('idx_lit_extraction_status'), table_name='literature', if_exists=True)

    logger.info("索引回滚完成")
