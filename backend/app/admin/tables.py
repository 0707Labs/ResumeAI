"""Shared pieces for admin tables: CSV export."""

import csv
import io
from datetime import UTC, datetime
from typing import Any

from fastapi.responses import Response
from pydantic import BaseModel


def cell(v: Any) -> str:
    """A CSV cell, defused: a leading = + - @ (or tab / CR) would run as a formula in a spreadsheet."""
    text = "" if v is None else v.isoformat() if isinstance(v, datetime) else str(v)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_response(rows: list[BaseModel], model: type[BaseModel], name: str) -> Response:
    out, fields = io.StringIO(), list(model.model_fields)
    writer = csv.writer(out)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([cell(getattr(row, f)) for f in fields])
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{name}-{datetime.now(UTC):%Y%m%d}.csv"',
        "Cache-Control": "no-store"})
