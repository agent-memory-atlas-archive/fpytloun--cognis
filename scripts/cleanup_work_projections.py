"""Explicit, bounded cleanup of retired Work projection versions (dry-run by default)."""

from __future__ import annotations

import argparse
import asyncio
import json

import sqlalchemy as sa

from cognis.api.chat_v2.work_materializer import WORK_MATERIALIZER_VERSION
from cognis.config import load_config
from cognis.store.database import create_engine, create_session_factory
from cognis.store.models import (
    WorkCurrentFileRow,
    WorkRecordFileRow,
    WorkRecordRow,
    WorkSessionProjectionRow,
)

TABLES = (WorkCurrentFileRow, WorkRecordFileRow, WorkRecordRow, WorkSessionProjectionRow)


async def cleanup(factory, *, versions: list[str], apply: bool = False, batch_size: int = 100):
    if not versions or WORK_MATERIALIZER_VERSION in versions:
        raise ValueError("Specify retired versions only; the current version is protected")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    result = {}
    async with factory() as db:
        for model in TABLES:
            predicate = model.materializer_version.in_(versions)
            count = await db.scalar(sa.select(sa.func.count()).select_from(model).where(predicate))
            deleted = 0
            if apply:
                if model is WorkRecordRow:
                    # Bound child deletion too: never cascade an unbounded file
                    # history from a single selected record.
                    predicate = sa.and_(
                        predicate,
                        ~sa.exists(
                            sa.select(WorkRecordFileRow.work_record_file_id).where(
                                WorkRecordFileRow.work_record_id == WorkRecordRow.work_record_id
                            )
                        ),
                    )
                primary_key = list(model.__table__.primary_key.columns)[0]
                ids = (
                    sa.select(primary_key).where(predicate).order_by(primary_key).limit(batch_size)
                )
                deleted = (
                    await db.execute(
                        sa.delete(model)
                        .where(predicate, primary_key.in_(ids))
                        .execution_options(synchronize_session=False)
                    )
                ).rowcount
            result[model.__tablename__] = {"eligible": count, "deleted": deleted}
        if apply:
            await db.commit()
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="append", required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-inactive",
        action="store_true",
        help="Confirm no running or rollback controller needs these versions",
    )
    args = parser.parse_args()
    if args.apply and not args.confirm_inactive:
        parser.error("--apply requires --confirm-inactive")
    engine = create_engine(load_config().database_url)
    try:
        result = await cleanup(
            create_session_factory(engine),
            versions=args.version,
            apply=args.apply,
            batch_size=args.batch_size,
        )
        print(json.dumps(result, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
