"""add_pathogen_monitoring

Revision ID: add_pathogen_monitoring
Revises: add_epidemiological_data_types
Create Date: 2026-09-18

Phase 2: new independent table for pathogen surveillance (病原学监测) data,
complementing antibody seroprevalence data with pathogen features
(strain/serotype/genotype/subtype/variant, detection rate, isolation count).

Additive: does not touch data_point table or existing rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_pathogen_monitoring'
down_revision: Union[str, Sequence[str], None] = 'add_epidemiological_data_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pathogen_monitoring',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('literature_id', sa.Uuid(), sa.ForeignKey('literature.id', ondelete='CASCADE'), index=True),
        sa.Column('disease', sa.String(100), index=True),
        sa.Column('pathogen_type', sa.String(50)),
        sa.Column('pathogen_name', sa.String(100), index=True),
        sa.Column('serotype', sa.String(50)),
        sa.Column('genotype', sa.String(50), index=True),
        sa.Column('subtype', sa.String(50)),
        sa.Column('lineage', sa.String(50)),
        sa.Column('variant_sites', sa.Text()),
        sa.Column('detection_rate', sa.Numeric(10, 4)),
        sa.Column('isolation_count', sa.Integer()),
        sa.Column('sample_size', sa.Integer()),
        sa.Column('detection_method', sa.String(200)),
        sa.Column('population', sa.String(200)),
        sa.Column('specimen', sa.String(100)),
        sa.Column('region', sa.String(100)),
        sa.Column('province', sa.String(100), index=True),
        sa.Column('city', sa.String(100)),
        sa.Column('collection_year', sa.Integer(), index=True),
        sa.Column('source_page', sa.Integer()),
        sa.Column('source_context', sa.Text()),
        sa.Column('review_status', sa.String(20), index=True),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )
    op.create_index('ix_pm_review_disease', 'pathogen_monitoring', ['review_status', 'disease'])


def downgrade() -> None:
    op.drop_index('ix_pm_review_disease', table_name='pathogen_monitoring')
    op.drop_table('pathogen_monitoring')