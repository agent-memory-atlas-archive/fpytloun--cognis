import json
import os
from urllib.parse import urlsplit

import pytest
from sqlalchemy import JSON, Column, Integer, MetaData, Table, insert, select, text

from cognis import json_codec
from cognis.store.database import create_engine


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
async def test_engine_json_compatibility_and_raw_serialization(tmp_path, backend):
    if backend == "sqlite":
        url = f"sqlite+aiosqlite:///{tmp_path / 'json.sqlite'}"
    else:
        url = os.getenv("COGNIS_TEST_RETENTION_POSTGRES_URL")
        if not url:
            pytest.skip("requires disposable PostgreSQL fixture")
        assert urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}
    engine = create_engine(url)
    values = [
        None,
        [],
        {},
        {"unicode": "Příliš 🐈", "nested": [True, False, None]},
        {"big": 2**100, "tiny": 1e-200, "negative_zero": -0.0},
    ]
    table = Table(
        "retention_json_fixture", MetaData(), Column("id", Integer), Column("value", JSON)
    )
    try:
        assert engine.sync_engine.dialect._json_deserializer is json_codec.decode
        # Writes remain the dialect's original standard JSON serializer.
        assert engine.sync_engine.dialect._json_serializer is None
        async with engine.begin() as connection:
            await connection.run_sync(table.create)
            for i, value in enumerate(values):
                await connection.execute(insert(table).values(id=i, value=value))
            actual = (
                (await connection.execute(select(table.c.value).order_by(table.c.id)))
                .scalars()
                .all()
            )
            assert actual == values
            raw = (
                (
                    await connection.execute(
                        text("SELECT CAST(value AS TEXT) FROM retention_json_fixture ORDER BY id")
                    )
                )
                .scalars()
                .all()
            )
            assert raw == [json.dumps(value) for value in values]
            await connection.run_sync(table.drop)
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    "document", ['{"duplicate":1,"duplicate":2}', '"\\ud800"', "NaN", "Infinity"]
)
def test_legacy_json_decode_fallbacks(document):
    actual, expected = json_codec.decode(document), json.loads(document)
    if document == "NaN":
        assert actual != actual and expected != expected
    else:
        assert actual == expected
