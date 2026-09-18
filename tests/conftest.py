import hashlib
import math
import os
import re
import uuid
from collections.abc import Iterator

import chromadb
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.main import create_app
from app.services.llm import LLMAnswer
from app.services.vector_store import VectorStore

# Must equal the vector column size, which is fixed by the migration (EMBEDDING_DIM).
DIM = 384
_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    """Deterministic hashed bag-of-words embedder.

    Texts that share words get similar vectors, so ranking in tests behaves like a
    real (if crude) semantic model without downloading anything.
    """

    model_name = "fake-embedder"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * DIM
        for word in _WORD.findall(text.lower()):
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeLLM:
    """Records every prompt and returns a fixed answer, or raises `error` when set."""

    provider = "fake-provider"
    model = "fake-model"

    def __init__(self, answer: str = "Cats purr when content [1].") -> None:
        self.answer = answer
        self.error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> LLMAnswer:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return LLMAnswer(text=self.answer, model=self.model)

    # Streaming: `error` fires before the first token; `mid_stream_error` after
    # `tokens_before_error` tokens.
    mid_stream_error: Exception | None = None
    tokens_before_error: int = 2

    def stream(self, system: str, user: str) -> Iterator[str]:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        for i, token in enumerate(self.answer.split(" ")):
            if self.mid_stream_error and i == self.tokens_before_error:
                raise self.mid_stream_error
            yield token if i == 0 else " " + token


# A superuser connection, used only to create and drop the per-run test database.
TEST_ADMIN_DATABASE_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL", "postgresql+psycopg://postgres:postgres@127.0.0.1:5434/postgres"
)
ROLES = {"sourcely_owner": "sourcely_owner", "sourcely_app": "sourcely_app"}


@pytest.fixture(scope="session")
def database_urls() -> Iterator[dict[str, str]]:
    """A fresh, migrated database for this test run. Yields the app and owner URLs.

    Mirrors docker/postgres/init.sql, so it also works on a bare Postgres such as the CI
    service container: roles are created if missing, then extensions and grants.
    """
    admin_url = make_url(TEST_ADMIN_DATABASE_URL)
    name = f"sourcely_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        connection = admin.connect()
    except OperationalError:
        pytest.exit(
            "Postgres isn't reachable at "
            f"{admin_url.render_as_string(hide_password=True)}. "
            "Start it with: docker compose up -d db",
            returncode=1,
        )
    with connection:
        for role, password in ROLES.items():
            exists = connection.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            ).scalar()
            if not exists:
                connection.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
        connection.execute(text(f'CREATE DATABASE "{name}" OWNER sourcely_owner'))

    db_admin = create_engine(admin_url.set(database=name), isolation_level="AUTOCOMMIT")
    with db_admin.connect() as connection:
        for statement in (
            "CREATE EXTENSION IF NOT EXISTS vector",
            "CREATE EXTENSION IF NOT EXISTS citext",
            "GRANT USAGE ON SCHEMA public TO sourcely_app",
            "ALTER DEFAULT PRIVILEGES FOR ROLE sourcely_owner IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sourcely_app",
            "ALTER DEFAULT PRIVILEGES FOR ROLE sourcely_owner IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO sourcely_app",
        ):
            connection.execute(text(statement))
    db_admin.dispose()

    def role_url(role: str) -> str:
        url = admin_url.set(username=role, password=ROLES[role], database=name)
        return url.render_as_string(hide_password=False)

    urls = {"app": role_url("sourcely_app"), "owner": role_url("sourcely_owner")}
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", urls["owner"])
    command.upgrade(config, "head")
    try:
        yield urls
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def clean_database(database_urls) -> dict[str, str]:
    """Empty every table (except Alembic's) so each test starts from the same state."""
    owner = create_engine(database_urls["owner"])
    with owner.begin() as connection:
        tables = (
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        if tables:
            connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
    owner.dispose()
    return database_urls


@pytest.fixture
def settings(clean_database) -> Settings:
    return Settings(
        _env_file=None,
        database_url=clean_database["app"],
        migration_database_url=clean_database["owner"],
        llm_provider="openai",
        openai_api_key="test-key",
        openai_model="fake-model",
        chunk_size=200,
        chunk_overlap=40,
        max_document_chars=5_000,
        min_relevance=0.2,
    )


@pytest.fixture
def store() -> VectorStore:
    # Ephemeral clients share one in-process database, so each test needs its own collection.
    return VectorStore(chromadb.EphemeralClient(), f"test-{uuid.uuid4().hex}")


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def client(settings, store, embedder, llm):
    app = create_app(settings, embedder=embedder, store=store, llm=llm)
    with TestClient(app) as c:
        yield c
