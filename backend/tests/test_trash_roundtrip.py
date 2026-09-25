"""Deleted personal records remain recoverable in local storage and Firebase."""

from src.api.routers import automation
from src.services.database import DatabaseService


class FakeFirestore:
    is_available = True

    def __init__(self):
        self.reminders = {}
        self.notes = {}

    def save_reminder(self, record_id, data):
        self.reminders[record_id] = {**self.reminders.get(record_id, {}), **data}
        return True

    def get_reminders(self, uid):
        return list(self.reminders.values())

    def save_note(self, record_id, data):
        self.notes[record_id] = {**self.notes.get(record_id, {}), **data}
        return True

    def get_notes(self, uid):
        return list(self.notes.values())


def test_reminder_trash_and_restore_persist_to_firestore(tmp_path, monkeypatch):
    db = DatabaseService(db_path=str(tmp_path / "trash.db"))
    fs = FakeFirestore()
    monkeypatch.setattr(automation, "_db", lambda: db)
    monkeypatch.setattr(automation, "_fs", lambda: fs)
    reminder = db.create_reminder("u", {"title": "Water", "activity": "STILL", "status": "COMPLETED"})

    automation.delete_reminder(reminder["id"], "u")
    assert db.get_reminder("u", reminder["id"])["status"] == "DELETED"
    assert fs.reminders[reminder["id"]]["previous_status"] == "COMPLETED"
    assert fs.reminders[reminder["id"]]["deleted_at"]

    automation.restore_reminder(reminder["id"], "u")
    assert db.get_reminder("u", reminder["id"])["status"] == "COMPLETED"
    assert fs.reminders[reminder["id"]]["deleted_at"] is None


def test_note_trash_and_restore_persist_to_firestore(tmp_path, monkeypatch):
    db = DatabaseService(db_path=str(tmp_path / "trash.db"))
    fs = FakeFirestore()
    monkeypatch.setattr(automation, "_db", lambda: db)
    monkeypatch.setattr(automation, "_fs", lambda: fs)
    note = db.create_note("u", {"content": "Odometer 4250 km"})

    automation.delete_note(note["id"], "u")
    assert db.list_notes("u") == []
    assert fs.notes[note["id"]]["deleted_at"]

    automation.restore_note(note["id"], "u")
    assert db.list_notes("u")[0]["id"] == note["id"]
    assert fs.notes[note["id"]]["deleted_at"] is None
