"""Postgres: the connection pool and the LangGraph checkpointer.

Create the tables once before first use:

    ./.venv/Scripts/python.exe -m app.db setup

That is a deliberate one-off rather than something the app does at startup.
`setup()` issues DDL, and several instances cold-starting at once would race
each other for it.
"""

import asyncio
import sys

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import get_settings

# All three of these are required, and each fails in its own confusing way.
#
#   autocommit        setup() runs DDL. Without this the tables are created
#                     inside a transaction that never commits.
#   prepare_threshold Neon's pooled endpoint is pgbouncer. Leave prepared
#                     statements on and the second request through a reused
#                     connection raises DuplicatePreparedStatement, which reads
#                     like a LangGraph bug and is not one.
#   row_factory       The saver indexes rows by column name.
CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}

_pool: AsyncConnectionPool | None = None


def use_selector_loop_on_windows() -> None:
    """psycopg's async mode refuses to run on the ProactorEventLoop, which is
    Windows' default. Linux is unaffected, so this only matters locally, and it
    has to run before anything creates a loop."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def get_pool() -> AsyncConnectionPool:
    """Opened on first use, then kept on the module.

    Serverless instances are reused between invocations, so the pool outlives a
    single request and the connection cost is paid per cold start rather than
    per question. Opening it at import would put that cost on /health too.
    """
    global _pool
    if _pool is None:
        settings = get_settings()
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is empty, so there is no pool to open")
        _pool = AsyncConnectionPool(
            settings.database_url,
            min_size=0,
            max_size=4,
            kwargs=CONNECTION_KWARGS,
            open=False,
        )
        await _pool.open(wait=True, timeout=15)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_checkpointer() -> AsyncPostgresSaver:
    return AsyncPostgresSaver(await get_pool())


async def setup() -> None:
    """Create the checkpoint tables. Idempotent, but run it deliberately."""
    checkpointer = await get_checkpointer()
    await checkpointer.setup()


async def _main() -> int:
    if sys.argv[1:2] != ["setup"]:
        print("usage: python -m app.db setup", file=sys.stderr)
        return 2
    await setup()
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "select table_name from information_schema.tables"
            " where table_schema = 'public' order by table_name"
        )
        names = [r["table_name"] for r in await cur.fetchall()]
    await close_pool()
    print("tables:", ", ".join(names) if names else "(none)")
    return 0


if __name__ == "__main__":
    use_selector_loop_on_windows()
    raise SystemExit(asyncio.run(_main()))
