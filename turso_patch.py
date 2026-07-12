"""
Turso HTTP adapter — pure Python, no Rust. Works on Render.
Monkey-patches sqlite3 to route exam_prep.db to Turso Cloud.
"""
import os, sqlite3, json, requests

TURSO_URL = os.environ.get("TURSO_DB_URL", "")
TURSO_AUTH=os.environ.get("TURSO_AUTH_TOKEN", "")
REST = TURSO_URL.replace("libsql://", "https://").split("?")[0] + "/v2/pipeline" if TURSO_URL else ""

class TR:
    def __init__(self, u, t):
        self.b = REST; self.h = {"Authorization": "Bearer "+t, "Content-Type": "application/json"}
    def execute(self, s, p=None):
        q = {"sql": s}
        if p:
            if isinstance(p, dict): q["named_args"] = [{k: v} for k, v in p.items()]
            elif isinstance(p, (tuple, list)): q["args"] = list(p)
            else: q["args"] = [p]
        r = requests.post(self.b, headers=self.h, json={"requests": [{"type": "execute", "stmt": q}]}, timeout=30)
        return TC(r.json().get("results", [{}])[0])
    def executemany(self, s, rows):
        if not rows: return
        rqs = []
        cols = None
        for params in rows:
            ss = s
            if params:
                for v in params:
                    if v is None: ss = ss.replace("?", "NULL", 1)
                    elif isinstance(v, (int, float)): ss = ss.replace("?", str(v), 1)
                    else:
                        escaped = str(v).replace("'", "''")
                        ss = ss.replace("?", f"'{escaped}'", 1)
            rqs.append({"type": "execute", "stmt": {"sql": ss}})
        requests.post(self.b, headers=self.h, json={"requests": rqs}, timeout=30)
    def commit(self): pass
    def close(self): pass
    def cursor(self): return self

class TC:
    def __init__(self, r):
        resp = r.get("response", {}); restype = resp.get("type", "")
        self._rows = []
        if restype == "execute":
            res = resp.get("result", {})
            if "rows" in res:
                for row in res["rows"]:
                    self._rows.append(tuple(v.get("value") if isinstance(v, dict) else v for v in row))
                if "cols" in res:
                    self.description = [(c.get("name", ""),) for c in res["cols"]]
        self._idx = 0; self.arraysize = 1
    def fetchone(self):
        if self._idx < len(self._rows): r = self._rows[self._idx]; self._idx += 1; return r
        return None
    def fetchall(self): return self._rows
    def __iter__(self): return iter(self._rows)
    def close(self): pass

_orig = sqlite3.connect
def _patch(database, *a, **kw):
    s = str(database)
    if TURSO_URL and TURSO_AUTH and "exam_prep" in s:
        return TR(TURSO_URL, TURSO_AUTH)
    return _orig(database, *a, **kw)
sqlite3.connect = _patch
