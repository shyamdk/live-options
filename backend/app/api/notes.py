from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import sqlite as db
from app.services import notes
from app.services.app_auth import require_auth

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteIn(BaseModel):
    day: str
    title: str = ""
    body: str
    tags: list[str] = []


def _clean(note: NoteIn) -> dict[str, Any]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", note.day):
        raise HTTPException(status_code=400, detail="day must be YYYY-MM-DD")
    if not note.body.strip():
        raise HTTPException(status_code=400, detail="The note is empty.")
    tags = sorted({t.strip().lower().replace(",", " ") for t in note.tags if t.strip()})
    return {"day": note.day, "title": note.title.strip(), "body": note.body.strip(), "tags": tags}


@router.get("", dependencies=[Depends(require_auth)])
async def list_notes() -> dict[str, Any]:
    return {"notes": db.list_notes()}


@router.post("", dependencies=[Depends(require_auth)])
async def create(note: NoteIn) -> dict[str, Any]:
    return db.create_note(**_clean(note))


@router.put("/{note_id}", dependencies=[Depends(require_auth)])
async def update(note_id: int, note: NoteIn) -> dict[str, Any]:
    saved = db.update_note(note_id, **_clean(note))
    if not saved:
        raise HTTPException(status_code=404, detail="Note not found.")
    return saved


@router.delete("/{note_id}", dependencies=[Depends(require_auth)])
async def delete(note_id: int) -> dict[str, Any]:
    if not db.delete_note(note_id):
        raise HTTPException(status_code=404, detail="Note not found.")
    return {"status": "deleted"}


@router.get("/summary", dependencies=[Depends(require_auth)])
async def summary() -> dict[str, Any]:
    return notes.summary()


@router.post("/summary/refresh", dependencies=[Depends(require_auth)])
async def refresh() -> dict[str, Any]:
    try:
        return await notes.refresh_digest()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Summary failed: {exc}") from exc
