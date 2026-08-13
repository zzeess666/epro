"""pymysql 数据库连接。"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor

from config.config import (
    DB_CHARSET,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)


def get_connection() -> Connection:
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset=DB_CHARSET,
        cursorclass=DictCursor,
        autocommit=False,
    )


@contextmanager
def db_cursor() -> Iterator[DictCursor]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
