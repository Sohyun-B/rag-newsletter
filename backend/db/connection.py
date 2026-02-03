import pyodbc
from contextlib import contextmanager
from typing import Any
import logging

from config import settings

logger = logging.getLogger(__name__)


def get_connection_string() -> str:
    """MSSQL 연결 문자열 생성"""
    return (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={settings.MSSQL_SERVER};"
        f"DATABASE={settings.MSSQL_DATABASE};"
        f"UID={settings.MSSQL_USER};"
        f"PWD={settings.MSSQL_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )


@contextmanager
def get_db_connection():
    """DB 연결 컨텍스트 매니저"""
    conn = None
    try:
        conn = pyodbc.connect(get_connection_string())
        yield conn
    except pyodbc.Error as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn:
            conn.close()


def execute_query(query: str, params: tuple = None) -> list[dict[str, Any]]:
    """SELECT 쿼리 실행, 결과를 딕셔너리 리스트로 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def execute_command(query: str, params: tuple = None) -> int:
    """INSERT/UPDATE/DELETE 실행, 영향받은 행 수 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        conn.commit()
        return cursor.rowcount


def execute_insert_returning_id(query: str, params: tuple = None) -> int:
    """INSERT 후 생성된 ID 반환"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params or ())
        cursor.execute("SELECT SCOPE_IDENTITY()")
        result = cursor.fetchone()
        new_id = result[0] if result else None
        conn.commit()
        return int(new_id) if new_id else None


def test_connection() -> bool:
    """DB 연결 테스트"""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            return True
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        return False
