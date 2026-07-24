import csv
import enum
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import json_value
from app.models import Base

BACKUP_FORMAT = "wealthportfolio-json-backup"
BACKUP_VERSION = 1


async def export_json_bytes(db: AsyncSession) -> bytes:
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in Base.metadata.sorted_tables:
        result = await db.execute(table.select())
        tables[table.name] = [
            {column: json_value(value) for column, value in dict(row._mapping).items()}
            for row in result.fetchall()
        ]
    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


async def export_csv_zip_bytes(db: AsyncSession) -> bytes:
    selected = {
        "owners",
        "institutions",
        "accounts",
        "instruments",
        "holdings",
        "transactions",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for table in Base.metadata.sorted_tables:
            if table.name not in selected:
                continue
            rows = [dict(row._mapping) for row in (await db.execute(table.select())).fetchall()]
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=[column.name for column in table.columns])
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else json_value(value) for key, value in row.items()})
            archive.writestr(f"{table.name}.csv", stream.getvalue().encode("utf-8-sig"))
    return output.getvalue()


def _deserialize(column: Any, value: Any) -> Any:
    if value is None:
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return value
    if python_type is uuid.UUID:
        return uuid.UUID(str(value))
    if python_type is Decimal:
        return Decimal(str(value))
    if python_type is datetime:
        return datetime.fromisoformat(str(value))
    if python_type is date:
        return date.fromisoformat(str(value))
    if isinstance(python_type, type) and issubclass(python_type, enum.Enum):
        return python_type(value)
    return value


async def restore_json_bytes(db: AsyncSession, content: bytes) -> dict[str, int]:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid_json_backup") from exc
    if payload.get("format") != BACKUP_FORMAT or payload.get("version") != BACKUP_VERSION:
        raise ValueError("unsupported_json_backup")
    tables_payload = payload.get("tables")
    if not isinstance(tables_payload, dict):
        raise ValueError("invalid_json_backup_tables")

    known_tables = {table.name: table for table in Base.metadata.sorted_tables}
    unknown = set(tables_payload) - set(known_tables)
    if unknown:
        raise ValueError("json_backup_contains_unknown_tables")

    restored: dict[str, int] = {}
    try:
        await db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for table in reversed(Base.metadata.sorted_tables):
            await db.execute(table.delete())
        for table in Base.metadata.sorted_tables:
            raw_rows = tables_payload.get(table.name, [])
            if not isinstance(raw_rows, list):
                raise ValueError(f"invalid_backup_table:{table.name}")
            rows = [
                {
                    column.name: _deserialize(column, raw[column.name])
                    for column in table.columns
                    if column.name in raw
                }
                for raw in raw_rows
            ]
            if rows:
                await db.execute(table.insert(), rows)
            restored[table.name] = len(rows)
        await db.commit()
        return restored
    except Exception:
        await db.rollback()
        raise
