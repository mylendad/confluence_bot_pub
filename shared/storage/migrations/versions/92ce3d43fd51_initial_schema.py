"""Initial schema

Revision ID: 92ce3d43fd51
Revises: 
Create Date: 2026-06-10 09:48:05.475540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92ce3d43fd51'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
    create table if not exists datamarts (
        name text primary key,
        code text,
        confluence_page_id text,
        confluence_url text,
        stakeholders_json text not null default '[]',
        updated_at text,
        facts_json text not null default '[]',
        release_changes_json text not null default '[]'
    );
    """)
    op.execute("""
    create table if not exists attributes (
        attribute_key text primary key,
        datamart_name text not null,
        payload_json text not null,
        content_hash text not null,
        parsed_at text not null
    );
    """)
    op.execute("create index if not exists idx_attributes_datamart on attributes(datamart_name);")
    op.execute("create index if not exists idx_attributes_target_field on attributes(json_extract(payload_json, '$.target_field'));")
    op.execute("""
    create table if not exists documents (
        id text primary key,
        text text not null,
        metadata_json text not null,
        content_hash text not null
    );
    """)
    op.execute("""
    create table if not exists change_log (
        id text primary key,
        datamart_name text,
        datamart_code text,
        entity_type text,
        entity_name text,
        change_type text,
        old_value text,
        new_value text,
        change_date text,
        detected_at text,
        source_url text,
        s2t_file_name text
    );
    """)
    op.execute("""
    create table if not exists s2t_state (
        resource_key text primary key,
        datamart_name text not null,
        page_id text,
        resource_type text,
        title text,
        file_name text,
        url text,
        metadata_json text not null,
        metadata_hash text not null,
        content_hash text,
        last_checked_at text not null,
        last_synced_at text,
        updated_at text
    );
    """)
    op.execute("create index if not exists idx_s2t_state_datamart on s2t_state(datamart_name);")
    op.execute("""
    create table if not exists chat_history (
        id integer primary key autoincrement,
        session_id text not null,
        user_message text not null,
        bot_response text not null,
        sources_json text not null default '[]',
        created_at text not null
    );
    """)
    op.execute("create index if not exists idx_chat_history_session on chat_history(session_id);")
    op.execute("""
    create table if not exists page_snapshots (
        datamart_page_id text primary key,
        version_map_json text not null,
        extracted_data_json text not null,
        updated_at text not null
    );
    """)

def downgrade() -> None:
    """Downgrade schema."""
    op.execute("drop table if exists page_snapshots;")
    op.execute("drop index if exists idx_chat_history_session;")
    op.execute("drop table if exists chat_history;")
    op.execute("drop index if exists idx_s2t_state_datamart;")
    op.execute("drop table if exists s2t_state;")
    op.execute("drop table if exists change_log;")
    op.execute("drop table if exists documents;")
    op.execute("drop index if exists idx_attributes_target_field;")
    op.execute("drop index if exists idx_attributes_datamart;")
    op.execute("drop table if exists attributes;")
    op.execute("drop table if exists datamarts;")
