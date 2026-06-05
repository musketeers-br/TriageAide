import hashlib
import json
import os
import sqlite3
import warnings


def _msg_type(msg):
    lc_id = msg.get("id", [])
    if isinstance(lc_id, list) and len(lc_id) >= 2:
        return lc_id[-1].lower().replace("message", "")
    kwargs = msg.get("kwargs", {})
    return kwargs.get("type", "")


def _normalize_cache_prompt(prompt_str):
    """Derive a cache key from user messages + tool call history only.

    Instead of hashing the full serialized prompt (which includes volatile
    fields that change between runs), we extract only:
    - The ordered list of HumanMessage contents (what the user said)
    - The ordered list of tool names called so far (intermediate state)

    This ensures:
    - Same user input + same tool flow = same key = cache hit (legitimate)
    - Different user messages or different tool history = cache miss
    - No stale-context responses from mismatched sessions
    """
    try:
        msgs = json.loads(prompt_str)
    except (json.JSONDecodeError, TypeError):
        return prompt_str
    user_contents = []
    tool_sequence = []
    for msg in msgs:
        mtype = _msg_type(msg)
        kwargs = msg.get("kwargs", {})
        if mtype == "human":
            content = kwargs.get("content", "")
            if content:
                user_contents.append(content)
        elif mtype == "tool":
            name = kwargs.get("name")
            if name:
                tool_sequence.append(name)
    return json.dumps(
        {"u": user_contents, "t": tool_sequence},
        sort_keys=True,
        ensure_ascii=False,
    )


def get_llm_cache(cache_namespace: str = ""):
    cache_type = os.getenv("LLM_CACHE", "").lower()
    if cache_type == "sqlite":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from langchain_community.cache import SQLiteCache
            default_db_path = os.path.join(os.path.expanduser("~"), ".cache", "langchain_cache.db")
            if cache_namespace:
                base, ext = os.path.splitext(default_db_path)
                default_db_path = f"{base}_{cache_namespace}{ext}"
            db_path = os.getenv("LLM_CACHE_DB_PATH", default_db_path)
            if cache_namespace and os.getenv("LLM_CACHE_DB_PATH"):
                base, ext = os.path.splitext(db_path)
                db_path = f"{base}_{cache_namespace}{ext}"
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            return _NormalizedSQLiteCache(database_path=db_path)
        except ImportError:
            print("WARNING: langchain-community not installed, LLM cache disabled")
            return None
    elif cache_type == "memory":
        from langchain_core.caches import InMemoryCache
        return InMemoryCache()
    return None


class _NormalizedSQLiteCache:
    """SQLiteCache wrapper that normalizes prompt keys to improve cache hit rates in agent flows."""

    def __init__(self, database_path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from langchain_core.caches import BaseCache
            from langchain_community.cache import SQLiteCache
        self._inner = SQLiteCache(database_path=database_path)
        BaseCache.register(_NormalizedSQLiteCache)

    def lookup(self, prompt, llm_string):
        return self._inner.lookup(_normalize_cache_prompt(prompt), llm_string)

    async def alookup(self, prompt, llm_string):
        return await self._inner.alookup(_normalize_cache_prompt(prompt), llm_string)

    def update(self, prompt, llm_string, return_val):
        return self._inner.update(_normalize_cache_prompt(prompt), llm_string, return_val)

    async def aupdate(self, prompt, llm_string, return_val):
        return await self._inner.aupdate(_normalize_cache_prompt(prompt), llm_string, return_val)

    def clear(self, **kwargs):
        return self._inner.clear(**kwargs)


class ToolCache:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_cache (
                key TEXT PRIMARY KEY,
                content TEXT,
                artifact TEXT,
                is_tuple INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def _make_key(self, tool_name, args):
        raw = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, tool_name, args):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT content, artifact, is_tuple FROM tool_cache WHERE key=?",
            (self._make_key(tool_name, args),),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        content = json.loads(row[0])
        if row[2]:
            artifact = json.loads(row[1])
            return (content, artifact)
        return content

    def set(self, tool_name, args, result):
        conn = sqlite3.connect(self.db_path)
        key = self._make_key(tool_name, args)
        if isinstance(result, tuple) and len(result) == 2:
            conn.execute(
                "INSERT OR REPLACE INTO tool_cache (key, content, artifact, is_tuple) VALUES (?, ?, ?, 1)",
                (key, json.dumps(result[0], ensure_ascii=False), json.dumps(result[1], ensure_ascii=False)),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO tool_cache (key, content, artifact, is_tuple) VALUES (?, ?, '', 0)",
                (key, json.dumps(result, ensure_ascii=False)),
            )
        conn.commit()
        conn.close()


def get_tool_cache(cache_namespace: str = ""):
    if os.getenv("LLM_CACHE", "").lower() not in ("sqlite",):
        return None
    default_db_path = os.path.join(os.path.expanduser("~"), ".cache", "tool_cache.db")
    if cache_namespace:
        base, ext = os.path.splitext(default_db_path)
        default_db_path = f"{base}_{cache_namespace}{ext}"
    db_path = os.getenv("TOOL_CACHE_DB_PATH", default_db_path)
    if cache_namespace and os.getenv("TOOL_CACHE_DB_PATH"):
        base, ext = os.path.splitext(db_path)
        db_path = f"{base}_{cache_namespace}{ext}"
    return ToolCache(db_path)


def wrap_tools_with_cache(tools, tool_cache):
    if not tool_cache:
        return tools
    cached_tools = []
    for tool in tools:
        original_coroutine = getattr(tool, "coroutine", None)
        if original_coroutine is None:
            cached_tools.append(tool)
            continue
        tool_name = tool.name
        _cache = tool_cache

        async def cached_async(*args, __original=original_coroutine, __name=tool_name, __cache=_cache, **kwargs):
            cache_kwargs = {k: v for k, v in kwargs.items() if k not in ("config", "callbacks", "run_manager", "tool_call_id")}
            try:
                all_args = {"args": [str(a) for a in args], "kwargs": cache_kwargs}
                hit = __cache.get(__name, all_args)
            except (TypeError, ValueError):
                hit = None
                all_args = None
            if hit is not None:
                return hit
            result = await __original(*args, **kwargs)
            if all_args is not None:
                try:
                    __cache.set(__name, all_args, result)
                except (TypeError, ValueError):
                    pass
            return result

        tool.coroutine = cached_async
        cached_tools.append(tool)
    return cached_tools
