from typing import Annotated

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_dashboard.db import get_db
from quant_dashboard.models import Note

app = FastAPI(title="Quant Dashboard", version="0.1.0")

DbSession = Annotated[Session, Depends(get_db)]


class HealthResponse(BaseModel):
    status: str


class NoteIn(BaseModel):
    text: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    text: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/notes", response_model=NoteOut, status_code=201)
def create_note(payload: NoteIn, db: DbSession) -> Note:
    note = Note(text=payload.text)
    db.add(note)
    db.commit()
    return note


@app.get("/notes", response_model=list[NoteOut])
def list_notes(db: DbSession) -> list[Note]:
    return list(db.scalars(select(Note).order_by(Note.id)))
