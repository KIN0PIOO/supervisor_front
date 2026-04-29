import os
from pathlib import Path

import oracledb
from dotenv import load_dotenv

from agents.sql_pipeline.core.logger import logger


# unified_agent/ 프로젝트 루트
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)

_CLIENT_INITIALIZED = False


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Required environment variable '{name}' is not set.")
    return value


def get_oracle_schema() -> str:
    return (os.getenv("ORACLE_SCHEMA") or "").strip().upper()


def qualify_table_name(table_name: str) -> str:
    schema = get_oracle_schema()
    clean_table = (table_name or "").strip()
    if not schema or not clean_table or "." in clean_table:
        return clean_table
    return f"{schema}.{clean_table}"


def split_table_owner_and_name(table_name: str) -> tuple[str | None, str]:
    clean_table = (table_name or "").strip().upper()
    if "." in clean_table:
        owner, name = clean_table.split(".", 1)
        return owner, name
    schema = get_oracle_schema()
    return (schema or None), clean_table


def get_connection():
    global _CLIENT_INITIALIZED

    if not _CLIENT_INITIALIZED:
        lib_dir = os.getenv("ORACLE_CLIENT_PATH")
        if lib_dir and os.path.exists(lib_dir):
            try:
                oracledb.init_oracle_client(lib_dir=lib_dir)
                logger.debug(f"[SqlPipeline:DB] Oracle Thick Mode 활성화 Path: {lib_dir}")
            except oracledb.ProgrammingError:
                pass
        _CLIENT_INITIALIZED = True

    user = _get_required_env("DB_USER")
    password = _get_required_env("DB_PASS")
    
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "1521")
    sid = os.getenv("DB_SID", "xe")
    
    if "/" in host or "(" in host:
        dsn = host
    else:
        dsn = f"{host}:{port}/{sid}"
        
    return oracledb.connect(user=user, password=password, dsn=dsn)


def get_mapping_rule_table() -> str:
    return qualify_table_name("NEXT_MIG_INFO")


def get_mapping_rule_detail_table() -> str:
    return qualify_table_name("NEXT_MIG_INFO_DTL")


def get_result_table() -> str:
    return qualify_table_name("NEXT_SQL_INFO")
