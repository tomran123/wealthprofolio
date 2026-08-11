import csv
import enum
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import json_value
from app.core.family_scope import explicitly_family_scoped, require_bound_family_id
from app.models import Base

BACKUP_FORMAT = "wealthportfolio-json-backup"
BACKUP_VERSION = 2

# Operational and secret-bearing rows are not part of a family data export.
# Full disaster-recovery backups are created out-of-band by the database
# platform and require a system administrator.
FAMILY_EXPORT_EXCLUDED_TABLES = {
    "background_jobs",
    "family_memberships",
    "llm_provider_configs",
}
IMMUTABLE_RESTORE_TABLES = {
    "transactions",
    "journal_entries",
    "journal_postings",
    "audit_events",
    "outbox_events",
}


def _family_export_tables():
    return [
        table
        for table in Base.metadata.sorted_tables
        if "family_id" in table.c
        and table.name not in FAMILY_EXPORT_EXCLUDED_TABLES
    ]


def _insertable_columns(table):
    # PostgreSQL generated columns (document_chunks.search_vector) are rebuilt
    # by the database and must never be supplied during restore.
    return [column for column in table.columns if column.computed is None]


def _family_select(db: AsyncSession, table, family_id: uuid.UUID):
    return explicitly_family_scoped(
        db,
        select(*_insertable_columns(table)).where(table.c.family_id == family_id),
    )


async def export_json_bytes(db: AsyncSession) -> bytes:
    family_id = require_bound_family_id(db)
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in _family_export_tables():
        result = await db.execute(_family_select(db, table, family_id))
        tables[table.name] = [
            {column: json_value(value) for column, value in dict(row._mapping).items()}
            for row in result.fetchall()
        ]
    payload = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "family_id": str(family_id),
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


async def export_csv_zip_bytes(db: AsyncSession) -> bytes:
    family_id = require_bound_family_id(db)
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
        for table in _family_export_tables():
            if table.name not in selected:
                continue
            rows = [
                dict(row._mapping)
                for row in (
                    await db.execute(_family_select(db, table, family_id))
                ).fetchall()
            ]
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(
                stream,
                fieldnames=[column.name for column in _insertable_columns(table)],
            )
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


def _normalize_restore_rows(
    tables_payload: dict[str, Any],
    known_tables: dict[str, Any],
    source_family_id: uuid.UUID,
) -> dict[str, list[dict[str, Any]]]:
    normalized: dict[str, list[dict[str, Any]]] = {}
    for table_name, table in known_tables.items():
        raw_rows = tables_payload.get(table_name, [])
        if not isinstance(raw_rows, list):
            raise ValueError(f"invalid_backup_table:{table_name}")
        known_columns = {column.name: column for column in table.columns}
        insertable_columns = {
            column.name: column for column in _insertable_columns(table)
        }
        rows: list[dict[str, Any]] = []
        seen_primary_keys: set[tuple[Any, ...]] = set()
        primary_key_names = [column.name for column in table.primary_key.columns]
        for raw in raw_rows:
            if not isinstance(raw, dict):
                raise ValueError(f"invalid_backup_row:{table_name}")
            if set(raw) - set(known_columns):
                raise ValueError(f"backup_row_contains_unknown_fields:{table_name}")
            try:
                row_family_id = uuid.UUID(str(raw.get("family_id")))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid_backup_row_family:{table_name}"
                ) from exc
            if row_family_id != source_family_id:
                raise ValueError(f"mixed_family_backup:{table_name}")

            row = {
                name: _deserialize(column, raw[name])
                for name, column in insertable_columns.items()
                if name in raw
            }
            row["family_id"] = source_family_id
            try:
                primary_key = tuple(row[name] for name in primary_key_names)
            except KeyError as exc:
                raise ValueError(
                    f"backup_row_missing_primary_key:{table_name}"
                ) from exc
            if any(value is None for value in primary_key):
                raise ValueError(f"backup_row_null_primary_key:{table_name}")
            if primary_key in seen_primary_keys:
                raise ValueError(f"backup_duplicate_primary_key:{table_name}")
            seen_primary_keys.add(primary_key)
            rows.append(row)
        normalized[table_name] = rows
    return normalized


def _validate_family_references(
    normalized: dict[str, list[dict[str, Any]]],
    known_tables: dict[str, Any],
) -> None:
    for source_name, source_table in known_tables.items():
        for constraint in source_table.foreign_key_constraints:
            elements = list(constraint.elements)
            if not elements:
                continue
            target_table = elements[0].column.table
            if target_table.name not in known_tables:
                # Users/families and other platform-owned rows are outside a
                # family export and are checked by normal database FKs.
                continue
            source_columns = [element.parent.name for element in elements]
            target_columns = [element.column.name for element in elements]
            target_keys = {
                tuple(row.get(column) for column in target_columns)
                for row in normalized[target_table.name]
            }
            for row in normalized[source_name]:
                key = tuple(row.get(column) for column in source_columns)
                if any(value is None for value in key):
                    continue
                if key not in target_keys:
                    raise ValueError(
                        f"backup_cross_reference_missing:"
                        f"{source_name}:{constraint.name or 'foreign_key'}"
                    )

    # DocumentLink.target_id is intentionally polymorphic and therefore has no
    # database FK. Sprint 1 currently permits only transaction links.
    for link in normalized.get("document_links", []):
        if link.get("target_type") != "transaction":
            raise ValueError("backup_unsupported_document_link_target")
        target_id = link.get("target_id")
        transaction_ids = {
            row.get("id") for row in normalized.get("transactions", [])
        }
        if target_id not in transaction_ids:
            raise ValueError("backup_cross_reference_missing:document_links:target_id")


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

    source_family_id = payload.get("family_id")
    try:
        source_family_uuid = uuid.UUID(str(source_family_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_json_backup_family") from exc
    target_family_id = require_bound_family_id(db)
    if source_family_uuid != target_family_id:
        # IDs are globally stable and referenced by audit/event rows. Silently
        # transplanting them into another family can collide with the source
        # tenant or rewrite identity, so cross-family cloning is a separate
        # explicit workflow rather than a restore side effect.
        raise ValueError("backup_family_mismatch")

    known_tables = {table.name: table for table in _family_export_tables()}
    unknown = set(tables_payload) - set(known_tables)
    if unknown:
        raise ValueError("json_backup_contains_unknown_tables")
    normalized = _normalize_restore_rows(
        tables_payload,
        known_tables,
        source_family_uuid,
    )
    _validate_family_references(normalized, known_tables)
    immutable_counts: dict[str, int] = {}
    for table_name in IMMUTABLE_RESTORE_TABLES:
        table = known_tables[table_name]
        immutable_counts[table_name] = int(
            (
                await db.execute(
                    explicitly_family_scoped(
                        db,
                        select(func.count()).select_from(table).where(
                            table.c.family_id == target_family_id
                        ),
                    )
                )
            ).scalar_one()
        )
    if any(immutable_counts.values()):
        # Posted events are immutable at the database layer. A family JSON
        # backup may seed an empty recovery tenant, but it must not rewrite a
        # live ledger. Full disaster recovery uses an isolated database restore
        # and cutover instead.
        raise ValueError("family_restore_requires_empty_ledger")

    restored: dict[str, int] = {}
    try:
        await db.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        for table in reversed(_family_export_tables()):
            if table.name in IMMUTABLE_RESTORE_TABLES:
                continue
            await db.execute(
                explicitly_family_scoped(
                    db,
                    table.delete().where(table.c.family_id == target_family_id),
                )
            )
        for table in _family_export_tables():
            rows = normalized[table.name]
            for row in rows:
                row["family_id"] = target_family_id
            if rows:
                await db.execute(
                    explicitly_family_scoped(db, table.insert()),
                    rows,
                )
            restored[table.name] = len(rows)
        await db.commit()
        return restored
    except Exception:
        await db.rollback()
        raise
