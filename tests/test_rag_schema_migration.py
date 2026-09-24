"""R-03 SQL 迁移的最小静态校验，不要求本机安装 Docker。"""

from pathlib import Path

MIGRATION = (
    Path(__file__).parents[1] / "db" / "migrations" / "001_rag_documents.sql"
)


def test_migration_contains_required_tables_and_extensions():
    """主路径验证：数据库扩展、三张核心表和必要索引都在迁移中。"""
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    for fragment in (
        "create extension if not exists vector",
        "create table if not exists documents",
        "create table if not exists document_chunks",
        "create table if not exists ingestion_runs",
        "using gin (content_tsv)",
        "using hnsw (embedding vector_cosine_ops)",
    ):
        assert fragment in sql


def test_migration_keeps_financial_date_and_source_guards():
    """关键边界验证：来源去重和未来数据时间线由数据库再次兜底。"""
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "source_hash char(64) not null unique" in sql
    assert "check (available_at >= published_at)" in sql
    assert "check (source_url ~ '^https?://')" in sql
    assert "on delete cascade" in sql
