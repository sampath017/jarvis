"""Bounded, portable conversation archives stored in the user's Drive."""
from datetime import datetime
import gzip
import io

from pydantic import BaseModel, Field, ConfigDict, AwareDatetime

MAX_COMPRESSED = 8 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024


class Message(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    text: str = Field(max_length=262144)
    is_user: bool
    timestamp: AwareDatetime
    run_id: str | None = None
    executed_records: list[str] = Field(default_factory=list, max_length=100)
    duration_ms: int | None = Field(default=None, ge=0)


class Conversation(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    title: str = Field(max_length=4096)
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(max_length=20000)


class Archive(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: str = Field(pattern='^jarvis_chat_backup$')
    version: int = Field(ge=1, le=1)
    session: Conversation


def verify(raw):
    if len(raw) > MAX_COMPRESSED:
        raise ValueError('Backup exceeds 8 MB')
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(MAX_EXPANDED + 1)
    if len(expanded) > MAX_EXPANDED:
        raise ValueError('Expanded backup exceeds 32 MB')
    return Archive.model_validate_json(expanded)
