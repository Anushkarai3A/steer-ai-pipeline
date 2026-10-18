"""add claim provenance source_id

Revision ID: c7f1a2d9e4b0
Revises: 178a4df7973c
Create Date: 2026-10-18 19:10:00.000000

Persist which source a claim was copied from during extraction. Provenance
only: the authoritative claim<->passage link stays in claim_evidence.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7f1a2d9e4b0'
down_revision: Union[str, None] = '178a4df7973c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('evidence_claims', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_id', sa.String(length=40), nullable=True))
        batch_op.create_foreign_key(
            'fk_evidence_claims_source_id',
            'research_sources', ['source_id'], ['id'], ondelete='SET NULL',
        )
        batch_op.create_index(batch_op.f('ix_evidence_claims_source_id'), ['source_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('evidence_claims', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evidence_claims_source_id'))
        batch_op.drop_constraint('fk_evidence_claims_source_id', type_='foreignkey')
        batch_op.drop_column('source_id')
