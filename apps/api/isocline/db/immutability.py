"""Application-level append-only guard for the audit log (PostgreSQL also enforces it with a trigger, see
migration 0001). Corrections are made by writing new records, never by rewriting history."""
from __future__ import annotations

from sqlalchemy import event

from isocline.db.models import AuditEvent


class ImmutableRecordError(Exception):
    pass


def _refuse(action):
    def handler(mapper, connection, target):
        raise ImmutableRecordError(f"{type(target).__name__} records are append-only ({action} refused)")
    return handler


def register_append_only(*classes) -> None:
    for cls in classes:
        event.listen(cls, "before_update", _refuse("update"))
        event.listen(cls, "before_delete", _refuse("delete"))


register_append_only(AuditEvent)
