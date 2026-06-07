import time
import asyncio
from dataclasses import dataclass, field


@dataclass
class VoiceSession:
    messages: list = field(default_factory=list)
    last_activity: float = field(default_factory=time.time)


class VoiceSessionStore:
    def __init__(self):
        self._sessions: dict = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> VoiceSession:
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = VoiceSession()
            session = self._sessions[session_id]
            session.last_activity = time.time()
            return session

    async def update_messages(self, session_id: str, messages: list) -> None:
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].messages = messages
                self._sessions[session_id].last_activity = time.time()

    async def evict_expired(self, ttl_seconds: int = 1800) -> int:
        now = time.time()
        async with self._lock:
            expired = [
                sid for sid, s in self._sessions.items()
                if now - s.last_activity > ttl_seconds
            ]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)
