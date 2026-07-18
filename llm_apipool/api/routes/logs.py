"""Log export/download API endpoints for llm-apipool."""

from __future__ import annotations

import csv
import io
import json as _json
import os
from typing import Any

from fastapi import APIRouter, Query, Response

from llm_apipool.key_store import KeyStore


def _create_logs_router(store: KeyStore) -> APIRouter:
    router = APIRouter()

    @router.get("/api/logs/audit/export")
    async def export_audit_log(
        format: str = Query("jsonl", pattern="^(csv|json|jsonl)$"),
        days: int = Query(30, ge=1, le=365),
        subscriber_id: str | None = None,
    ) -> Response:
        """Export audit log entries in CSV, JSON, or JSONL format."""
        entries: list[dict[str, Any]] = store.get_audit_log(
            subscriber_id=subscriber_id, days=days, limit=10000
        )

        if format == "csv":
            output = io.StringIO()
            if entries:
                writer = csv.DictWriter(output, fieldnames=list(entries[0].keys()))
                writer.writeheader()
                writer.writerows(entries)
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=audit-{days}d.csv"
                    )
                },
            )

        if format == "json":
            return Response(
                content=_json.dumps(entries, indent=2, default=str),
                media_type="application/json",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=audit-{days}d.json"
                    )
                },
            )

        # jsonl
        lines = "\n".join(_json.dumps(e, default=str) for e in entries)
        return Response(
            content=lines,
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=audit-{days}d.jsonl"
                )
            },
        )

    @router.get("/api/logs/access")
    async def get_access_logs(
        date: str | None = Query(None, pattern="^\\d{4}-\\d{2}-\\d{2}$"),
        limit: int = Query(200, ge=1, le=5000),
    ) -> dict[str, Any]:
        """Read access log entries from JSONL files."""
        from llm_apipool.proxy_logger import read_entries

        entries = read_entries(days=1 if not date else None, limit=limit)
        return {"entries": entries, "count": len(entries)}

    @router.get("/api/logs/info")
    async def log_info() -> dict[str, Any]:
        """Get log storage info (file sizes, days available)."""
        from llm_apipool.proxy_logger import list_log_days

        log_dir = os.path.expanduser("~/.llm-apipool/logs")
        total_size = 0
        if os.path.isdir(log_dir):
            for f in os.listdir(log_dir):
                fp = os.path.join(log_dir, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
        return {
            "log_directory": log_dir,
            "total_size_bytes": total_size,
            "days_available": list_log_days(),
        }

    return router


__all__ = ["_create_logs_router"]
