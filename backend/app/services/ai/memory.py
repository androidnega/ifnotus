"""Persistent AI memory, undo snapshots, and safe path helpers."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings


SENSITIVE_KEY = re.compile(
    r"(password|secret|api[_-]?key|token|private[_-]?key|passwd|authorization)",
    re.I,
)


class AiMemoryStore:
    """File-backed memory + undo journal under `.ifnotus/ai/` (or a scoped root)."""

    def __init__(self, settings: Settings, *, root: Path | str | None = None) -> None:
        self._root = Path(root).resolve() if root else Path(settings.ai_memory_path).resolve()
        self._memory_file = self._root / "memory.json"
        self._undo_file = self._root / "undo.json"

    def _ensure(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def _read(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write(self, path: Path, data: Any) -> None:
        self._ensure()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def list_notes(self, limit: int = 30) -> list[dict[str, Any]]:
        data = self._read(self._memory_file, {"notes": []})
        notes = data.get("notes") or []
        return list(reversed(notes[-limit:]))

    def remember(self, title: str, content: str, *, tags: list[str] | None = None) -> dict[str, Any]:
        data = self._read(self._memory_file, {"notes": []})
        note = {
            "id": str(uuid.uuid4()),
            "title": title.strip()[:120],
            "content": content.strip()[:4000],
            "tags": tags or [],
            "created_at": datetime.now(UTC).isoformat(),
        }
        notes = data.get("notes") or []
        notes.append(note)
        data["notes"] = notes[-200:]
        self._write(self._memory_file, data)
        return note

    def recall(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        q = query.lower().strip()
        notes = self.list_notes(limit=200)
        if not q:
            return notes[:limit]
        scored = []
        for note in notes:
            blob = f"{note.get('title','')} {note.get('content','')} {' '.join(note.get('tags') or [])}".lower()
            if q in blob:
                scored.append(note)
        return scored[:limit]

    def push_undo(
        self,
        *,
        action_type: str,
        path: str | None,
        previous_content: str | None,
        new_content: str | None,
        app_id: str | None,
        root_id: str | None,
        summary: str,
        absolute_path: str | None = None,
    ) -> dict[str, Any]:
        data = self._read(self._undo_file, {"entries": []})
        entry = {
            "id": str(uuid.uuid4()),
            "action_type": action_type,
            "path": path,
            "absolute_path": absolute_path,
            "previous_content": previous_content,
            "new_content": new_content,
            "app_id": app_id,
            "root_id": root_id,
            "summary": summary[:300],
            "created_at": datetime.now(UTC).isoformat(),
        }
        entries = data.get("entries") or []
        entries.append(entry)
        data["entries"] = entries[-50:]
        self._write(self._undo_file, data)
        return {"id": entry["id"], "summary": entry["summary"]}

    def pop_undo(self) -> dict[str, Any] | None:
        data = self._read(self._undo_file, {"entries": []})
        entries = data.get("entries") or []
        if not entries:
            return None
        entry = entries.pop()
        data["entries"] = entries
        self._write(self._undo_file, data)
        return entry

    def list_undo(self, limit: int = 10) -> list[dict[str, Any]]:
        data = self._read(self._undo_file, {"entries": []})
        entries = data.get("entries") or []
        return [
            {
                "id": e.get("id"),
                "summary": e.get("summary"),
                "path": e.get("path"),
                "action_type": e.get("action_type"),
                "created_at": e.get("created_at"),
            }
            for e in reversed(entries[-limit:])
        ]

    # ── Conversation history (persists until user deletes) ──────────────

    @property
    def _sessions_file(self) -> Path:
        return self._root / "sessions.json"

    def list_sessions(
        self, *, surface: str | None = None, path: str | None = None, limit: int = 40
    ) -> list[dict[str, Any]]:
        data = self._read(self._sessions_file, {"sessions": []})
        sessions = data.get("sessions") or []
        if surface:
            sessions = [s for s in sessions if s.get("surface") == surface]
        if path is not None:
            want = path.strip()
            sessions = [s for s in sessions if (s.get("path") or "").strip() == want]
        sessions = sorted(sessions, key=lambda s: s.get("updated_at") or "", reverse=True)
        out = []
        for s in sessions[:limit]:
            out.append(
                {
                    "id": s.get("id"),
                    "title": s.get("title"),
                    "surface": s.get("surface"),
                    "path": s.get("path"),
                    "app_id": s.get("app_id"),
                    "root_id": s.get("root_id"),
                    "message_count": len(s.get("messages") or []),
                    "created_at": s.get("created_at"),
                    "updated_at": s.get("updated_at"),
                }
            )
        return out

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        data = self._read(self._sessions_file, {"sessions": []})
        for s in data.get("sessions") or []:
            if s.get("id") == session_id:
                return s
        return None

    def create_session(
        self,
        *,
        surface: str,
        title: str | None = None,
        path: str | None = None,
        app_id: str | None = None,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        data = self._read(self._sessions_file, {"sessions": []})
        now = datetime.now(UTC).isoformat()
        session = {
            "id": str(uuid.uuid4()),
            "title": (title or "New conversation").strip()[:120],
            "surface": surface,
            "path": path,
            "app_id": app_id,
            "root_id": root_id,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        sessions = data.get("sessions") or []
        sessions.append(session)
        data["sessions"] = sessions[-100:]
        self._write(self._sessions_file, data)
        return session

    def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        title: str | None = None,
    ) -> dict[str, Any] | None:
        data = self._read(self._sessions_file, {"sessions": []})
        sessions = data.get("sessions") or []
        for s in sessions:
            if s.get("id") != session_id:
                continue
            existing = s.get("messages") or []
            for m in messages:
                existing.append(
                    {
                        "id": m.get("id") or str(uuid.uuid4()),
                        "role": m.get("role"),
                        "content": str(m.get("content") or "")[:50000],
                    }
                )
            s["messages"] = existing[-300:]
            if title and (not s.get("title") or s.get("title") == "New conversation"):
                s["title"] = title.strip()[:120]
            s["updated_at"] = datetime.now(UTC).isoformat()
            self._write(self._sessions_file, data)
            return s
        return None

    def delete_session(self, session_id: str) -> bool:
        data = self._read(self._sessions_file, {"sessions": []})
        sessions = data.get("sessions") or []
        next_sessions = [s for s in sessions if s.get("id") != session_id]
        if len(next_sessions) == len(sessions):
            return False
        data["sessions"] = next_sessions
        self._write(self._sessions_file, data)
        return True

    def clear_sessions(self, *, surface: str | None = None) -> int:
        data = self._read(self._sessions_file, {"sessions": []})
        sessions = data.get("sessions") or []
        if surface:
            kept = [s for s in sessions if s.get("surface") != surface]
            removed = len(sessions) - len(kept)
            data["sessions"] = kept
        else:
            removed = len(sessions)
            data["sessions"] = []
        self._write(self._sessions_file, data)
        return removed


def mask_secrets(text: str) -> str:
    """Redact likely secrets from tool output / previews."""
    lines = []
    for line in text.splitlines():
        if "=" in line and SENSITIVE_KEY.search(line.split("=", 1)[0]):
            key = line.split("=", 1)[0]
            lines.append(f"{key}=***REDACTED***")
        elif SENSITIVE_KEY.search(line) and (":" in line or "Bearer" in line):
            lines.append(re.sub(r"(Bearer\s+)\S+", r"\1***REDACTED***", line, flags=re.I))
        else:
            lines.append(line)
    return "\n".join(lines)


_CUSTOMER_ABS = re.compile(
    r"(?:/srv/apps/ifnotus-customers|/var/www/ifnotus-customers|/home/[^/\s]+/ifnotus-customers)"
    r"/[^\s`\"'<>)\]]+"
)


def mask_site_paths(text: str, document_root: str | None = None) -> str:
    """Hide absolute tenant host paths; show clean site-relative paths only."""
    if not text:
        return text
    doc = (document_root or "").rstrip("/")

    def _rel(match: re.Match[str]) -> str:
        abs_path = match.group(0).rstrip("/")
        if doc and (abs_path == doc or abs_path.startswith(doc + "/")):
            rel = abs_path[len(doc) :].lstrip("/")
            return rel or "site root"
        # /…/ifnotus-customers/<id>/rest → rest
        parts = abs_path.split("/ifnotus-customers/", 1)
        if len(parts) == 2:
            rest = parts[1]
            segs = rest.split("/", 1)
            if len(segs) == 2:
                return segs[1] or "site root"
            return "site root"
        return "site root"

    out = _CUSTOMER_ABS.sub(_rel, text)
    # Catch bare prefix mentions
    out = re.sub(r"/srv/apps/ifnotus-customers\b", "site root", out)
    out = re.sub(r"ifnotus-customers/[0-9a-f-]{8,}", "site", out, flags=re.I)
    return out
