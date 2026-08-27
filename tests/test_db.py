"""Connection settings and the graph's behaviour without a database.

Nothing here connects to Postgres. The connection settings are worth a test
anyway: all three look like boilerplate, all three are load bearing, and each
one fails in a way that points somewhere other than the cause.
"""

import pytest

from app.agent.graph import build_graph
from app.config import Settings
from app.db import CONNECTION_KWARGS, get_pool

FAKE_KEY = "not-a-real-key-nothing-here-calls-the-api"


def test_autocommit_is_on() -> None:
    # setup() issues DDL. Without autocommit the checkpoint tables are created
    # inside a transaction that is never committed, and the next run finds
    # nothing there.
    assert CONNECTION_KWARGS["autocommit"] is True


def test_prepared_statements_are_disabled() -> None:
    # Neon's pooled endpoint is pgbouncer. With prepared statements on, the
    # second request over a reused connection raises DuplicatePreparedStatement,
    # which reads like a LangGraph bug and is not one.
    assert CONNECTION_KWARGS["prepare_threshold"] == 0


def test_rows_come_back_as_dicts() -> None:
    # The saver indexes rows by column name.
    from psycopg.rows import dict_row

    assert CONNECTION_KWARGS["row_factory"] is dict_row


async def test_pool_refuses_to_open_without_a_url() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        await get_pool()


def test_graph_compiles_without_a_checkpointer() -> None:
    # Tests should not need a database to prove the loop routes correctly, so
    # the checkpointer stays optional. Without one the agent answers and
    # forgets, which is the right shape here.
    graph = build_graph(Settings(llm_api_key=FAKE_KEY))
    assert "agent" in graph.get_graph().nodes
