import os
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not configured. "
        "Please create a .env file."
    )


@contextmanager
def get_connection():
    """
    Create and manage a PostgreSQL database connection.
    """
    conn = psycopg.connect(DATABASE_URL)

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
