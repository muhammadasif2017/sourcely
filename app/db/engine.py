"""Creating the database engine and checking that the database answers."""

from sqlalchemy import Engine, create_engine, text


def make_engine(url: str, connect_timeout: int = 5) -> Engine:
    """A connection pool for `url`. `pool_pre_ping` replaces connections the server dropped.

    `connect_timeout` (seconds) bounds how long a request, or `/health`, waits for an
    unreachable database. Without it psycopg waits for the operating system, which on Windows
    can take minutes when a firewall drops the connection attempt.
    """
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": connect_timeout})


def database_ok(engine: Engine) -> bool:
    """True when a trivial query succeeds. Never raises."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
