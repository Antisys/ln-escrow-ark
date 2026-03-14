"""initial schema baseline

Revision ID: 320927bb680c
Revises:
Create Date: 2026-02-26 20:17:25.940442

Safe baseline migration:
- For FRESH installs: creates the deals table with all current columns
- For EXISTING databases: no-op (table already exists, stamp with `alembic stamp head`)
- Does NOT drop any legacy tables or columns — those are left in place
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '320927bb680c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'deals' in existing_tables:
        # Existing database — nothing to do.
        # Run `alembic stamp head` to mark this revision as applied.
        return

    # Fresh install — create the deals table from scratch
    op.create_table(
        'deals',
        sa.Column('deal_id', sa.String(length=36), nullable=False),
        sa.Column('deal_link_token', sa.String(length=32), nullable=False),
        sa.Column('creator_role', sa.String(length=10), nullable=False),
        sa.Column('seller_id', sa.String(length=100), nullable=True),
        sa.Column('seller_name', sa.String(length=100), nullable=True),
        sa.Column('buyer_id', sa.String(length=100), nullable=True),
        sa.Column('buyer_name', sa.String(length=100), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price_sats', sa.BigInteger(), nullable=False),
        sa.Column('timeout_hours', sa.Integer(), nullable=False),
        sa.Column('timeout_action', sa.String(length=20), nullable=False),
        sa.Column('requires_tracking', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('tracking_carrier', sa.String(length=50), nullable=True),
        sa.Column('tracking_number', sa.String(length=100), nullable=True),
        sa.Column('shipping_notes', sa.Text(), nullable=True),
        sa.Column('invoice_amount_sats', sa.BigInteger(), nullable=True),
        sa.Column('service_fee_sats', sa.Integer(), nullable=True),
        sa.Column('chain_fee_budget_sats', sa.Integer(), nullable=True),
        sa.Column('ln_payment_hash', sa.String(length=64), nullable=True),
        sa.Column('ln_invoice', sa.Text(), nullable=True),
        sa.Column('ln_operation_id', sa.String(length=100), nullable=True),
        sa.Column('buyer_pubkey', sa.String(length=66), nullable=True),
        sa.Column('seller_pubkey', sa.String(length=66), nullable=True),
        sa.Column('buyer_linking_pubkey', sa.String(length=66), nullable=True),
        sa.Column('seller_linking_pubkey', sa.String(length=66), nullable=True),
        sa.Column('buyer_auth_verified', sa.Boolean(), nullable=True),
        sa.Column('seller_auth_verified', sa.Boolean(), nullable=True),
        sa.Column('buyer_auth_signature', sa.Text(), nullable=True),
        sa.Column('seller_auth_signature', sa.Text(), nullable=True),
        sa.Column('seller_payout_invoice', sa.Text(), nullable=True),
        sa.Column('payout_status', sa.String(length=20), nullable=True),
        sa.Column('payout_fee_sat', sa.Integer(), nullable=True),
        sa.Column('buyer_payout_invoice', sa.Text(), nullable=True),
        sa.Column('buyer_payout_status', sa.String(length=20), nullable=True),
        sa.Column('buyer_payout_fee_sat', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('buyer_started_at', sa.DateTime(), nullable=True),
        sa.Column('buyer_joined_at', sa.DateTime(), nullable=True),
        sa.Column('funded_at', sa.DateTime(), nullable=True),
        sa.Column('shipped_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('release_txid', sa.String(length=100), nullable=True),
        sa.Column('refund_txid', sa.String(length=100), nullable=True),
        sa.Column('ark_secret_code_hash', sa.String(length=64), nullable=True),
        sa.Column('signing_phase', sa.String(length=30), nullable=False, server_default='initial'),
        sa.Column('invoice_bolt11', sa.Text(), nullable=True),
        sa.Column('buyer_recovery_contact', sa.String(length=200), nullable=True),
        sa.Column('seller_recovery_contact', sa.String(length=200), nullable=True),
        sa.Column('ark_escrow_deal_id', sa.String(length=100), nullable=True),
        sa.Column('ark_timeout_block', sa.Integer(), nullable=True),
        sa.Column('disputed_at', sa.DateTime(), nullable=True),
        sa.Column('disputed_by', sa.String(length=100), nullable=True),
        sa.Column('dispute_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('deal_id'),
    )

    # Indexes
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.create_index('ix_deals_deal_link_token', ['deal_link_token'], unique=True)
        batch_op.create_index('ix_deals_seller_id', ['seller_id'], unique=False)
        batch_op.create_index('ix_deals_buyer_id', ['buyer_id'], unique=False)
        batch_op.create_index('ix_deals_status', ['status'], unique=False)
        batch_op.create_index('ix_deals_ln_payment_hash', ['ln_payment_hash'], unique=False)
        batch_op.create_index('ix_deals_created_at', ['created_at'], unique=False)
        batch_op.create_index('ix_deals_expires_at', ['expires_at'], unique=False)
        batch_op.create_index('ix_deals_ark_escrow_deal_id', ['ark_escrow_deal_id'], unique=False)
        batch_op.create_index('ix_deals_status_created', ['status', 'created_at'], unique=False)
        batch_op.create_index('ix_deals_token', ['deal_link_token'], unique=False)


def downgrade() -> None:
    op.drop_table('deals')
