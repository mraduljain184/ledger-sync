import os
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DSN = os.getenv("DATABASE_URL", "postgresql://ledger:ledger@localhost:5433/ledger")

pool = None


def open_pool():
    global pool
    pool = ConnectionPool(DSN, min_size=1, max_size=10,
                          kwargs={"row_factory": dict_row}, open=False)
    pool.open()


def close_pool():
    pool.close()


def init_schema():
    path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(path) as f:
        sql = f.read()
    with pool.connection() as conn:
        conn.execute(sql)