import re
import time
import asyncio
from dataclasses import dataclass, field

_PT_BR_TOKENS = frozenset({
    "tenho", "estou", "sinto", "dor", "febre", "tosse", "cansaco", "cansaço",
    "hoje", "dias", "semanas", "meses", "sim", "nao", "não", "oi", "ola", "olá",
    "bom", "quero", "preciso", "meu", "minha", "paciente", "consulta",
    "triagem", "medico", "médico", "pressao", "pressão", "sangue", "pulmao",
    "pulmão", "remedio", "remédio", "faz", "fazer", "ajuda", "inicio", "início",
    "iniciar", "começar", "comeco", "começo", "para", "pela", "pelo",
    "uma", "umas", "uns", "também", "tambem", "sintomas", "sintoma",
    "dores", "cansado", "cansada", "tossindo", "coração",
})


def detect_language(text: str) -> str:
    """Return 'pt-BR' if Portuguese indicators found, else 'auto'."""
    if not text:
        return "auto"
    words = set(re.sub(r"[^\w\s]", "", text.lower()).split())
    return "pt-BR" if words & _PT_BR_TOKENS else "auto"


@dataclass
class VoiceSession:
    messages: list = field(default_factory=list)
    language: str = ""
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

    async def update_language(self, session_id: str, language: str) -> None:
        async with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].language = language

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
