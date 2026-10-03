import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


@contextmanager
def get_connection():
    """
    Create and manage a PostgreSQL database connection.

    The DATABASE_URL check is deliberately done here, at connection time,
    not at module import time. Some platforms (FastMCP Cloud / Prefect
    Horizon included) statically import this module to inspect the server's
    tools during their build step, before any runtime environment variables
    are available — an import-time check would fail that step even though
    the real deployment has DATABASE_URL set correctly at runtime.
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it as an environment variable "
            "in your deployment platform, or in a local .env file for "
            "development — see .env_example."
        )

    conn = psycopg.connect(DATABASE_URL)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()