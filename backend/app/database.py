import asyncio, base64, json, os, sqlite3, urllib.error, urllib.request
from .config import get_settings

SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS files (
 id TEXT PRIMARY KEY,
 original_filename TEXT NOT NULL,
 stored_filename TEXT NOT NULL UNIQUE,
 mime_type TEXT NOT NULL,
 file_size INTEGER NOT NULL CHECK(file_size >= 0),
 file_blob BLOB NOT NULL,
 deletion_token_hash TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
)""",
    "CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at)",
]
LIMIT_WORDS = ("too large", "quota", "limit", "full", "exceed")


class DatabaseUnavailable(Exception): pass
class StorageLimit(Exception): pass


def _enc(v):
    if v is None: return {"type": "null"}
    if isinstance(v, (bytes, bytearray, memoryview)): return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, bool): return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int): return {"type": "integer", "value": str(v)}
    if isinstance(v, float): return {"type": "float", "value": v}
    return {"type": "text", "value": str(v)}


def _dec(v):
    t = v.get("type")
    if t == "null": return None
    if t == "integer": return int(v["value"])
    if t == "float": return float(v["value"])
    if t == "blob":
        b = v["base64"]
        return base64.b64decode(b + "=" * (-len(b) % 4))
    return v.get("value")


class TursoHttp:
    """Minimal Turso/libSQL client over the Hrana-over-HTTP pipeline API (pure Python,
    stateless, so it suits serverless runtimes such as Vercel)."""
    def __init__(self, url: str, token: str, timeout: float):
        url = url.strip(); token = token.strip()  # env vars pasted with a trailing newline/space are common
        if "://" not in url: url = "https://" + url
        for a, b in (("libsql://", "https://"), ("wss://", "https://"), ("ws://", "http://")):
            if url.startswith(a): url = b + url[len(a):]; break
        self.endpoint = url.rstrip("/") + "/v2/pipeline"
        self.token = token; self.timeout = timeout

    def run(self, statements):
        """statements: list of (sql, params). Returns a list of (rows, affected_rows, cols)."""
        reqs = [{"type": "execute", "stmt": {"sql": s, "args": [_enc(p) for p in params]}} for s, params in statements]
        reqs.append({"type": "close"})
        req = urllib.request.Request(self.endpoint, data=json.dumps({"requests": reqs}).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r: body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read(2000).decode("utf-8", "replace").lower()
            if e.code == 413 or any(w in msg for w in LIMIT_WORDS): raise StorageLimit(f"HTTP {e.code}") from None
            raise DatabaseUnavailable(f"Turso HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise DatabaseUnavailable(f"Turso connection failed: {type(e).__name__}") from None
        out = []
        for res in body.get("results", [])[:len(statements)]:
            if res.get("type") == "error":
                m = (res.get("error") or {}).get("message", "error")
                if any(w in m.lower() for w in LIMIT_WORDS): raise StorageLimit(m)
                raise DatabaseUnavailable(m)
            r = res["response"]["result"]
            cols = [c.get("name") for c in r.get("cols", [])]
            out.append(([[_dec(c) for c in row] for row in r.get("rows", [])], r.get("affected_row_count", 0), cols))
        return out


class Database:
    def __init__(self):
        self.conn = None; self.http = None; self.ready = False; self.lock = asyncio.Lock()

    async def connect(self):
        if self.ready: return
        s = get_settings(); url = s.turso_database_url.strip()
        local = url.startswith("file:") or url.endswith(".db")
        try:
            if local:
                if os.environ.get("VERCEL"):
                    raise DatabaseUnavailable("TURSO_DATABASE_URL must be a libsql:// URL on Vercel (filesystem is read-only/ephemeral)")
                self.conn = sqlite3.connect(url.removeprefix("file:"), check_same_thread=False)
                await self._run(lambda: (self.conn.executescript(";\n".join(SCHEMA_STATEMENTS) + ";"), self.conn.commit()))
            else:
                self.http = TursoHttp(url, s.turso_auth_token, s.database_timeout)
                await self._run(lambda: self.http.run([(q, ()) for q in SCHEMA_STATEMENTS]))
            self.ready = True
        except (DatabaseUnavailable, StorageLimit): raise
        except Exception as e: raise DatabaseUnavailable(str(e)) from e

    async def close(self):
        if self.conn:
            try: await self._run(self.conn.close)
            except Exception: pass
        self.conn = None; self.http = None; self.ready = False

    async def _run(self, fn):
        try: return await asyncio.wait_for(asyncio.to_thread(fn), get_settings().database_timeout + 5)
        except (sqlite3.OperationalError, TimeoutError) as e: raise DatabaseUnavailable(str(e)) from e

    def _wrap(self, e):
        if isinstance(e, (DatabaseUnavailable, StorageLimit)): return e
        if any(x in str(e).lower() for x in LIMIT_WORDS): return StorageLimit(str(e))
        return DatabaseUnavailable(str(e))

    async def execute(self, sql: str, params: tuple = ()):
        await self.connect()
        try:
            if self.http: return (await self._run(lambda: self.http.run([(sql, params)])))[0][1]
            async with self.lock:
                def op():
                    cur = self.conn.execute(sql, params); self.conn.commit(); return cur.rowcount
                return await self._run(op)
        except Exception as e: raise self._wrap(e) from e

    async def fetchone(self, sql: str, params: tuple = ()):
        await self.connect()
        try:
            if self.http:
                rows, _, cols = (await self._run(lambda: self.http.run([(sql, params)])))[0]
                return dict(zip(cols, rows[0])) if rows else None
            async with self.lock:
                def op():
                    cur = self.conn.execute(sql, params); row = cur.fetchone()
                    return dict(zip([d[0] for d in cur.description], row)) if row else None
                return await self._run(op)
        except Exception as e: raise self._wrap(e) from e


db = Database()
