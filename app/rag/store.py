"""The vector store: schema, embedding, and similarity search.

Written directly against psycopg rather than through a vector-store library.
The corpus is three essays, the pool is already configured correctly for Neon's
pgbouncer endpoint, and a library would bring its own connection handling that
would need the same treatment. Similarity search over a table this small is a
sequential scan, and that is the right answer at this size.
"""

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import Settings, get_settings
from app.db import get_pool

# Separate statements on purpose. psycopg refuses to send several commands in
# one execute, so keeping them apart is required rather than stylistic.
SCHEMA = (
    "create extension if not exists vector",
    """
    create table if not exists writing_chunks (
        id bigserial primary key,
        route text not null,
        title text not null,
        chunk_index int not null,
        content text not null,
        embedding vector({dimensions}) not null,
        unique (route, chunk_index)
    )
    """,
)


def embedder(settings: Settings, *, for_query: bool) -> GoogleGenerativeAIEmbeddings:
    """Gemini wants to know whether it is embedding a document or a question.

    The two are asymmetric: a question and the passage answering it do not look
    alike, and telling the model which side it is on is what makes them land
    near each other. Getting this wrong costs retrieval quality quietly.
    """
    return GoogleGenerativeAIEmbeddings(
        model=settings.embedding_model,
        google_api_key=settings.llm_api_key,
        output_dimensionality=settings.embedding_dimensions,
        task_type="RETRIEVAL_QUERY" if for_query else "RETRIEVAL_DOCUMENT",
    )


def as_vector(values: list[float]) -> str:
    """pgvector's text input format. Passing the list and casting with ::vector
    avoids depending on the pgvector package just to register a type."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


async def create_schema() -> None:
    settings = get_settings()
    pool = await get_pool()
    async with pool.connection() as conn:
        for statement in SCHEMA:
            await conn.execute(statement.format(dimensions=settings.embedding_dimensions))


async def replace_route(route: str, title: str, chunks: list[str]) -> int:
    """Re-ingest one page. Deletes its old chunks first, so a shortened essay
    does not leave orphans behind that still answer questions."""
    settings = get_settings()
    vectors = await embedder(settings, for_query=False).aembed_documents(chunks)
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute("delete from writing_chunks where route = %s", (route,))
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            await conn.execute(
                "insert into writing_chunks (route, title, chunk_index, content, embedding)"
                " values (%s, %s, %s, %s, %s::vector)",
                (route, title, index, chunk, as_vector(vector)),
            )
    return len(chunks)


async def search(query: str, limit: int = 4) -> list[dict]:
    """Nearest chunks by cosine distance, closest first."""
    settings = get_settings()
    vector = as_vector(await embedder(settings, for_query=True).aembed_query(query))
    pool = await get_pool()
    async with pool.connection() as conn:
        cursor = await conn.execute(
            "select route, title, content, 1 - (embedding <=> %s::vector) as score"
            " from writing_chunks order by embedding <=> %s::vector limit %s",
            (vector, vector, limit),
        )
        return await cursor.fetchall()
