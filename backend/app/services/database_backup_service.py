import asyncio
import os
from urllib.parse import unquote

from sqlalchemy.engine import make_url

from app.core.config import get_settings

settings = get_settings()


def _connection_args() -> tuple[list[str], dict[str, str]]:
    url = make_url(settings.database_url)
    args: list[str] = []
    if url.host:
        args.extend(["--host", url.host])
    if url.port:
        args.extend(["--port", str(url.port)])
    if url.username:
        args.extend(["--username", unquote(url.username)])
    if url.database:
        args.extend(["--dbname", url.database])
    env = dict(os.environ)
    if url.password:
        env["PGPASSWORD"] = unquote(url.password)
    return args, env


async def create_sql_backup() -> bytes:
    connection_args, env = _connection_args()
    try:
        process = await asyncio.create_subprocess_exec(
            "pg_dump",
            *connection_args,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--format=plain",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("pg_dump_not_available") from exc
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"pg_dump_failed:{stderr.decode('utf-8', errors='replace')[:500]}")
    if len(stdout) > settings.backup_max_bytes:
        raise RuntimeError("database_backup_too_large")
    return stdout


async def restore_sql_backup(content: bytes) -> None:
    if len(content) > settings.backup_max_bytes:
        raise ValueError("database_backup_too_large")
    connection_args, env = _connection_args()
    try:
        process = await asyncio.create_subprocess_exec(
            "psql",
            *connection_args,
            "--single-transaction",
            "--set=ON_ERROR_STOP=1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("psql_not_available") from exc
    _, stderr = await process.communicate(content)
    if process.returncode != 0:
        raise RuntimeError(f"database_restore_failed:{stderr.decode('utf-8', errors='replace')[:500]}")
