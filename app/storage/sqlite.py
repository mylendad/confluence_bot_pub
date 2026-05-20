import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class SQLite:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                create table if not exists datamarts (
                    name text primary key,
                    code text,
                    confluence_page_id text,
                    confluence_url text,
                    stakeholders_json text not null default '[]',
                    updated_at text
                );
                create table if not exists attributes (
                    attribute_key text primary key,
                    datamart_name text not null,
                    payload_json text not null,
                    content_hash text not null,
                    parsed_at text not null
                );
                create index if not exists idx_attributes_datamart on attributes(datamart_name);
                create index if not exists idx_attributes_target_field
                    on attributes(json_extract(payload_json, '$.target_field'));
                create table if not exists documents (
                    id text primary key,
                    text text not null,
                    metadata_json text not null,
                    content_hash text not null
                );
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
                create index if not exists idx_s2t_state_datamart
                    on s2t_state(datamart_name);
                """
            )
