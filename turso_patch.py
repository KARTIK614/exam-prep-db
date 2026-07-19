"""
Turso HTTP adapter — pure Python, no Rust. Works on Render.
Monkey-patches sqlite3 so any connection to a path containing "exam_prep"
is routed to the Turso Cloud REST endpoint via the Hrana v2 pipeline API.

Provides sqlite3.Row-compatible rows (both integer and string indexing),
plus executescript() so schema init works over HTTP.
"""
import os
import sqlite3
import requests

TURSO_URL = os.environ.get("TURSO_DB_URL", "")
TURSO_AUTH = os.environ.get("TURSO_AUTH_TOKEN", "")
REST = TURSO_URL.replace("libsql://", "https://").split("?")[0] + "/v2/pipeline" if TURSO_URL else ""


class Row:
    """sqlite3.Row-compatible: supports row[0], row['col'], iter(row), len(row), .keys(), .get()."""
    __slots__ = ("_values", "_map")

    def __init__(self, values, cols):
        self._values = tuple(values)
        self._map = {c: v for c, v in zip(cols, values)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def get(self, key, default=None):
        return self._map.get(key, default)

    def keys(self):
        return list(self._map.keys())

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __contains__(self, key):
        return key in self._map

    def __repr__(self):
        return f"Row({self._map!r})"


def _typed_arg(v):
    """Convert a Python value to Hrana v2 typed-arg dict."""
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        import base64
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _build_stmt(sql, params):
    stmt = {"sql": sql}
    if params is None:
        return stmt
    if isinstance(params, dict):
        stmt["named_args"] = [{"name": k, "value": _typed_arg(v)} for k, v in params.items()]
    elif isinstance(params, (list, tuple)):
        stmt["args"] = [_typed_arg(v) for v in params]
    else:
        stmt["args"] = [_typed_arg(params)]
    return stmt


def _post(requests_list, timeout=30):
    """POST a list of Hrana requests. Raise if HTTP failed or Hrana returned a per-request error.

    Hrana v2 pipeline replies with HTTP 200 even when individual statements fail —
    each entry in `results` is either {"type": "ok", "response": {...}} or
    {"type": "error", "error": {"message": ..., "code": ...}}. Historically we
    only raised on HTTP non-2xx, so schema errors (bad column, missing table)
    silently produced empty cursors with lastrowid=None. Now we inspect every
    entry and raise sqlite3.OperationalError on the first failure, including
    the failing SQL when we can identify it from `requests_list`.
    """
    r = requests.post(
        REST,
        headers={"Authorization": "Bearer " + TURSO_AUTH, "Content-Type": "application/json"},
        json={"requests": requests_list},
        timeout=timeout,
    )
    r.raise_for_status()
    payload = r.json()
    results = payload.get("results", []) or []
    for idx, entry in enumerate(results):
        if entry.get("type") == "error":
            err = entry.get("error", {}) or {}
            msg = err.get("message", "unknown Turso/Hrana error")
            code = err.get("code", "")
            # Best-effort: pull the SQL out of the matching request so the
            # traceback names the failing statement.
            sql_ctx = ""
            try:
                sql_ctx = requests_list[idx].get("stmt", {}).get("sql", "")
            except (IndexError, AttributeError, TypeError):
                pass
            detail = f"Turso: {msg}"
            if code:
                detail += f" [code={code}]"
            if sql_ctx:
                detail += f" | sql={sql_ctx[:200]}"
            raise sqlite3.OperationalError(detail)
    return payload


class TC:
    """Cursor-like object holding the parsed rows of one Hrana `execute` response."""

    def __init__(self, result_envelope):
        # Error entries are already raised in _post — by the time we get here
        # the envelope is either an OK execute response or an empty sentinel
        # (executemany calls TC({}) after the underlying POSTs succeeded).
        resp = result_envelope.get("response", {}) or {}
        restype = resp.get("type", "")
        self._rows = []
        self._cols = []
        self.description = None
        self.lastrowid = None
        self._idx = 0
        self.arraysize = 1

        if restype == "execute":
            res = resp.get("result", {}) or {}
            self._cols = [c.get("name", "") for c in res.get("cols", [])]
            for row in res.get("rows", []):
                values = [v.get("value") if isinstance(v, dict) else v for v in row]
                # Coerce integer strings back to ints (Hrana returns integers as strings).
                for i, v in enumerate(values):
                    if isinstance(v, str) and isinstance(row[i], dict) and row[i].get("type") == "integer":
                        try:
                            values[i] = int(v)
                        except ValueError:
                            pass
                    elif isinstance(row[i], dict) and row[i].get("type") == "null":
                        values[i] = None
                self._rows.append(Row(values, self._cols))
            if self._cols:
                self.description = [(c,) for c in self._cols]
            lri = res.get("last_insert_rowid")
            if lri is not None:
                try:
                    self.lastrowid = int(lri)
                except (TypeError, ValueError):
                    self.lastrowid = lri

    def fetchone(self):
        if self._idx < len(self._rows):
            r = self._rows[self._idx]
            self._idx += 1
            return r
        return None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def close(self):
        pass


class TR:
    """Connection-like object. Delegates SQL to the Turso HTTP endpoint."""

    def __init__(self, url, token):
        self.url = url
        self.token = token
        self.row_factory = None  # kept for API compatibility; ignored (rows are always Row).

    def execute(self, sql, params=None):
        payload = _post([{"type": "execute", "stmt": _build_stmt(sql, params)}])
        results = payload.get("results", [{}])
        return TC(results[0])

    def executemany(self, sql, rows_iter):
        rows = list(rows_iter or [])
        if not rows:
            return TC({})
        reqs = [{"type": "execute", "stmt": _build_stmt(sql, r)} for r in rows]
        # Send in chunks of 50 to stay under Turso payload limits. Any chunk
        # that fails raises inside _post — we let it propagate. Keep the last
        # successful chunk's final envelope so the returned cursor reflects
        # last_insert_rowid of the tail row (matches sqlite3 semantics for
        # executemany more closely than the previous empty-TC sentinel).
        last_payload = None
        for i in range(0, len(reqs), 50):
            last_payload = _post(reqs[i:i + 50], timeout=60)
        if last_payload:
            tail_results = last_payload.get("results", []) or []
            if tail_results:
                return TC(tail_results[-1])
        return TC({})

    def executescript(self, script):
        """Execute a multi-statement SQL script (semicolon-separated)."""
        stmts = _split_sql(script)
        if not stmts:
            return
        reqs = [{"type": "execute", "stmt": {"sql": s}} for s in stmts]
        for i in range(0, len(reqs), 50):
            _post(reqs[i:i + 50], timeout=60)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass

    def cursor(self):
        return self


def _split_sql(script):
    """Split a SQL script into individual statements, respecting single-quoted strings."""
    stmts = []
    buf = []
    in_string = False
    i = 0
    while i < len(script):
        ch = script[i]
        if ch == "'":
            # Handle '' escape inside a string.
            if in_string and i + 1 < len(script) and script[i + 1] == "'":
                buf.append("''")
                i += 2
                continue
            in_string = not in_string
            buf.append(ch)
        elif ch == ";" and not in_string:
            piece = "".join(buf).strip()
            if piece:
                stmts.append(piece)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


_orig_connect = sqlite3.connect


def _patched_connect(database, *args, **kwargs):
    s = str(database)
    if TURSO_URL and TURSO_AUTH and "exam_prep" in s:
        return TR(TURSO_URL, TURSO_AUTH)
    return _orig_connect(database, *args, **kwargs)


sqlite3.connect = _patched_connect
