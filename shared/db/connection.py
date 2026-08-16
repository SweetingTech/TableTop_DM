import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager


DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(conn=None, dict_cursor=True):
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    try:
        factory = psycopg2.extras.RealDictCursor if dict_cursor else None
        cur = conn.cursor(cursor_factory=factory)
        yield cur
        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        cur.close()
        if own_conn:
            conn.close()


@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_principal_id(conn, principal_id):
    with conn.cursor() as cur:
        cur.execute("SET LOCAL app.principal_id = %s", (str(principal_id),))


def execute_query(query, params=None, fetch=True, conn=None):
    with get_cursor(conn=conn) as cur:
        cur.execute(query, params)
        if fetch:
            return cur.fetchall()
        return None


def execute_one(query, params=None, conn=None):
    with get_cursor(conn=conn) as cur:
        cur.execute(query, params)
        return cur.fetchone()
