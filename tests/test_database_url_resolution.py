from __future__ import annotations

from platform_app.config import PlatformSettings
from platform_app.db.session import get_migration_database_url
from pydantic import SecretStr


def test_migration_database_url_reads_file_backed_secret(tmp_path) -> None:
    secret_path = tmp_path / "database_url"
    expected = "postgresql+psycopg://platform:example@postgres/platform"
    secret_path.write_text(expected + "\n", encoding="utf-8")
    settings = PlatformSettings(
        database_url=None,
        database_url_file=str(secret_path),
    )

    assert get_migration_database_url(settings) == expected


def test_migration_database_url_prefers_direct_setting(tmp_path) -> None:
    secret_path = tmp_path / "database_url"
    secret_path.write_text(
        "postgresql+psycopg://platform:file@postgres/platform",
        encoding="utf-8",
    )
    expected = "postgresql+psycopg://platform:direct@postgres/platform"
    settings = PlatformSettings(
        database_url=SecretStr(expected),
        database_url_file=str(secret_path),
    )

    assert get_migration_database_url(settings) == expected
