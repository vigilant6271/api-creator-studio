
from __future__ import annotations
import hashlib, json, re, secrets, sqlite3, time
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
DB_PATH = Path(__import__("os").environ.get("API_STUDIO_DB", BASE.parent / "studio.db"))
app = FastAPI(title="API Creator Studio", version="0.1.0", description="Build and test custom APIs.")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          slug TEXT NOT NULL UNIQUE, api_key_hash TEXT, created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS endpoints (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          method TEXT NOT NULL, path TEXT NOT NULL, name TEXT NOT NULL, summary TEXT DEFAULT '',
          handler TEXT NOT NULL DEFAULT 'static', resource TEXT DEFAULT '',
          status_code INTEGER NOT NULL DEFAULT 200, response_json TEXT NOT NULL DEFAULT '{}',
          request_schema TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL,
          UNIQUE(project_id, method, path)
        );
        CREATE TABLE IF NOT EXISTS records (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          resource TEXT NOT NULL, data_json TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          method TEXT NOT NULL, path TEXT NOT NULL, status INTEGER NOT NULL, duration_ms REAL NOT NULL,
          response_json TEXT NOT NULL, created_at REAL NOT NULL
        );
        """)
        if not c.execute("SELECT id FROM projects WHERE slug='starter-api'").fetchone():
            cur = c.execute("INSERT INTO projects(name,slug,created_at) VALUES(?,?,?)",
                            ("Starter API", "starter-api", time.time()))
            pid = cur.lastrowid
            samples = [
                {"id": 1, "name": "Ada Lovelace", "email": "ada@example.com"},
                {"id": 2, "name": "Grace Hopper", "email": "grace@example.com"},
            ]
            for item in samples:
                c.execute("INSERT INTO records(project_id,resource,data_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                          (pid, "users", json.dumps(item), time.time(), time.time()))
            starter = [
                ("GET", "/users", "List users", "Return all users", "crud", "users", 200, "[]"),
                ("GET", "/users/{id}", "Get user", "Return one user by id", "crud", "users", 200, "{}"),
                ("POST", "/users", "Create user", "Create a user", "crud", "users", 201, "{}"),
            ]
            for row in starter:
                c.execute("""INSERT INTO endpoints(project_id,method,path,name,summary,handler,resource,status_code,response_json,created_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""", (pid, *row, time.time()))

init_db()

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)

class EndpointIn(BaseModel):
    method: str
    path: str
    name: str
    summary: str = ""
    handler: str = "static"
    resource: str = ""
    status_code: int = 200
    response_json: Any = {}
    request_schema: Any = {}

class RecordIn(BaseModel):
    data: dict[str, Any]

def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "api"

def project_row(row):
    return {"id": row["id"], "name": row["name"], "slug": row["slug"],
            "auth_enabled": bool(row["api_key_hash"]), "created_at": row["created_at"]}

def get_project(c, slug):
    row = c.execute("SELECT * FROM projects WHERE slug=?", (slug,)).fetchone()
    if not row: raise HTTPException(404, "Project not found")
    return row

def validate_path(path: str):
    if not path.startswith("/") or path == "/" or " " in path or "//" in path:
        raise HTTPException(422, "Path must start with / and contain no spaces or double slashes")
    if not re.fullmatch(r"/[A-Za-z0-9_{}./-]+", path):
        raise HTTPException(422, "Path contains unsupported characters")
    if path.count("{") != path.count("}") or re.search(r"\{[^{}]+\}", path) is None and ("{" in path or "}" in path):
        raise HTTPException(422, "Invalid path parameter syntax")
    return path

def route_match(pattern: str, actual: str):
    p = pattern.strip("/").split("/") if pattern.strip("/") else []
    a = actual.strip("/").split("/") if actual.strip("/") else []
    if len(p) != len(a): return None
    params = {}
    for expected, got in zip(p, a):
        if expected.startswith("{") and expected.endswith("}"):
            params[expected[1:-1]] = got
        elif expected != got:
            return None
    return params

@app.get("/", response_class=HTMLResponse)
def home():
    return (BASE / "static" / "index.html").read_text()

@app.get("/api/projects")
def list_projects():
    with db() as c:
        return [project_row(r) for r in c.execute("SELECT * FROM projects ORDER BY id")]

@app.post("/api/projects")
def create_project(body: ProjectIn):
    slug = slugify(body.name)
    with db() as c:
        base, n = slug, 2
        while c.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone():
            slug = f"{base}-{n}"; n += 1
        cur = c.execute("INSERT INTO projects(name,slug,created_at) VALUES(?,?,?)", (body.name, slug, time.time()))
        return project_row(c.execute("SELECT * FROM projects WHERE id=?", (cur.lastrowid,)).fetchone())

@app.patch("/api/projects/{project_id}")
def rename_project(project_id: int, body: ProjectIn):
    with db() as c:
        row = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row: raise HTTPException(404, "Project not found")
        c.execute("UPDATE projects SET name=? WHERE id=?", (body.name, project_id))
        return project_row(c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with db() as c:
        if not c.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        c.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"deleted": True}

@app.get("/api/projects/{slug}/endpoints")
def list_endpoints(slug: str):
    with db() as c:
        p = get_project(c, slug)
        rows = c.execute("SELECT * FROM endpoints WHERE project_id=? ORDER BY id", (p["id"],)).fetchall()
        return [endpoint_row(r) for r in rows]

def endpoint_row(r):
    return {**dict(r), "response_json": json.loads(r["response_json"]), "request_schema": json.loads(r["request_schema"])}

@app.post("/api/projects/{slug}/endpoints")
def create_endpoint(slug: str, body: EndpointIn):
    method = body.method.upper()
    if method not in {"GET","POST","PUT","PATCH","DELETE"}: raise HTTPException(422, "Unsupported HTTP method")
    validate_path(body.path)
    if body.handler not in {"static","crud"}: raise HTTPException(422, "Handler must be static or crud")
    if body.handler == "crud" and not body.resource: raise HTTPException(422, "CRUD handlers need a resource name")
    with db() as c:
        p = get_project(c, slug)
        try:
            cur = c.execute("""INSERT INTO endpoints(project_id,method,path,name,summary,handler,resource,status_code,response_json,request_schema,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (p["id"], method, body.path, body.name, body.summary, body.handler, body.resource,
               body.status_code, json.dumps(body.response_json), json.dumps(body.request_schema), time.time()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "An endpoint with this method and path already exists")
        return endpoint_row(c.execute("SELECT * FROM endpoints WHERE id=?", (cur.lastrowid,)).fetchone())

@app.put("/api/endpoints/{endpoint_id}")
def update_endpoint(endpoint_id: int, body: EndpointIn):
    method = body.method.upper(); validate_path(body.path)
    if method not in {"GET","POST","PUT","PATCH","DELETE"}: raise HTTPException(422, "Unsupported HTTP method")
    if body.handler not in {"static","crud"}: raise HTTPException(422, "Handler must be static or crud")
    with db() as c:
        old = c.execute("SELECT * FROM endpoints WHERE id=?", (endpoint_id,)).fetchone()
        if not old: raise HTTPException(404, "Endpoint not found")
        try:
            c.execute("""UPDATE endpoints SET method=?,path=?,name=?,summary=?,handler=?,resource=?,status_code=?,response_json=?,request_schema=? WHERE id=?""",
                (method,body.path,body.name,body.summary,body.handler,body.resource,body.status_code,
                 json.dumps(body.response_json),json.dumps(body.request_schema),endpoint_id))
        except sqlite3.IntegrityError: raise HTTPException(409, "Duplicate method and path")
        return endpoint_row(c.execute("SELECT * FROM endpoints WHERE id=?", (endpoint_id,)).fetchone())

@app.delete("/api/endpoints/{endpoint_id}")
def delete_endpoint(endpoint_id: int):
    with db() as c:
        c.execute("DELETE FROM endpoints WHERE id=?", (endpoint_id,))
    return {"deleted": True}

@app.get("/api/projects/{slug}/records/{resource}")
def list_records(slug: str, resource: str):
    with db() as c:
        p = get_project(c, slug)
        rows = c.execute("SELECT * FROM records WHERE project_id=? AND resource=? ORDER BY id", (p["id"], resource)).fetchall()
        return [json.loads(r["data_json"]) for r in rows]

@app.post("/api/projects/{slug}/records/{resource}")
def add_record(slug: str, resource: str, body: RecordIn):
    with db() as c:
        p = get_project(c, slug); now = time.time()
        data = dict(body.data)
        cur = c.execute("INSERT INTO records(project_id,resource,data_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (p["id"],resource,json.dumps(data),now,now))
        data.setdefault("id", cur.lastrowid)
        c.execute("UPDATE records SET data_json=? WHERE id=?", (json.dumps(data),cur.lastrowid))
        return data

@app.get("/api/projects/{slug}/openapi.json")
def openapi(slug: str):
    with db() as c:
        p = get_project(c, slug)
        rows = c.execute("SELECT * FROM endpoints WHERE project_id=?", (p["id"],)).fetchall()
    paths = {}
    for r in rows:
        path = re.sub(r"\{([^}]+)\}", r"{\1}", r["path"])
        paths.setdefault(path,{})[r["method"].lower()] = {
            "summary": r["summary"] or r["name"],
            "operationId": re.sub(r"[^a-zA-Z0-9]+","_",r["name"]).strip("_"),
            "responses": {str(r["status_code"]): {"description":"Configured response",
                "content":{"application/json":{"schema":{"type":"object"}}}}},
            "x-api-creator-handler": r["handler"]
        }
    return {"openapi":"3.1.0","info":{"title":p["name"],"version":"1.0.0"},"servers":[{"url":f"/runtime/{p['slug']}"}],"paths":paths}

@app.get("/api/projects/{slug}/export")
def export_project(slug: str):
    with db() as c:
        p = get_project(c, slug)
        eps = [endpoint_row(r) for r in c.execute("SELECT * FROM endpoints WHERE project_id=?", (p["id"],))]
        resources = {}
        for r in c.execute("SELECT resource,data_json FROM records WHERE project_id=?", (p["id"],)):
            resources.setdefault(r["resource"], []).append(json.loads(r["data_json"]))
    return {"name":p["name"],"slug":p["slug"],"endpoints":eps,"resources":resources}

@app.post("/api/projects/import")
def import_project(payload: dict[str, Any]):
    name = str(payload.get("name") or "Imported API")[:80]
    with db() as c:
        slug = slugify(name); base=slug; i=2
        while c.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone():
            slug=f"{base}-{i}"; i+=1
        cur=c.execute("INSERT INTO projects(name,slug,created_at) VALUES(?,?,?)",(name,slug,time.time()))
        pid=cur.lastrowid
        for ep in payload.get("endpoints",[]):
            method=str(ep.get("method","GET")).upper(); path=validate_path(str(ep.get("path","/items")))
            if method not in {"GET","POST","PUT","PATCH","DELETE"}: continue
            c.execute("""INSERT OR IGNORE INTO endpoints(project_id,method,path,name,summary,handler,resource,status_code,response_json,request_schema,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(pid,method,path,ep.get("name","Imported endpoint"),ep.get("summary",""),
              ep.get("handler","static"),ep.get("resource",""),int(ep.get("status_code",200)),
              json.dumps(ep.get("response_json",{})),json.dumps(ep.get("request_schema",{})),time.time()))
        for resource, records in payload.get("resources",{}).items():
            for record in records:
                c.execute("INSERT INTO records(project_id,resource,data_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                          (pid,resource,json.dumps(record),time.time(),time.time()))
        return project_row(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())

@app.post("/api/projects/{slug}/keys")
def create_api_key(slug: str):
    key = "acs_" + secrets.token_urlsafe(28)
    with db() as c:
        p=get_project(c,slug)
        c.execute("UPDATE projects SET api_key_hash=? WHERE id=?", (hashlib.sha256(key.encode()).hexdigest(),p["id"]))
    return {"api_key":key,"warning":"Copy this key now. It cannot be shown again."}

@app.delete("/api/projects/{slug}/keys")
def revoke_api_key(slug: str):
    with db() as c:
        p=get_project(c,slug); c.execute("UPDATE projects SET api_key_hash=NULL WHERE id=?",(p["id"],))
    return {"revoked":True}

def execute_crud(c, project, ep, params, request, body):
    resource=ep["resource"]
    item_id=params.get("id")
    if request.method == "GET":
        if item_id:
            row=c.execute("SELECT data_json FROM records WHERE project_id=? AND resource=? AND json_extract(data_json,'$.id')=?",
                          (project["id"],resource,str(item_id))).fetchone()
            if not row:
                row=c.execute("SELECT data_json FROM records WHERE project_id=? AND resource=? AND id=?",
                              (project["id"],resource,int(item_id) if str(item_id).isdigit() else -1)).fetchone()
            if not row: raise HTTPException(404,"Record not found")
            return json.loads(row["data_json"]),200
        return [json.loads(r["data_json"]) for r in c.execute("SELECT data_json FROM records WHERE project_id=? AND resource=? ORDER BY id",
                                                               (project["id"],resource))],200
    if request.method == "POST":
        data=body if isinstance(body,dict) else {}
        now=time.time()
        cur=c.execute("INSERT INTO records(project_id,resource,data_json,created_at,updated_at) VALUES(?,?,?,?,?)",
                      (project["id"],resource,json.dumps(data),now,now))
        data=dict(data); data.setdefault("id",cur.lastrowid)
        c.execute("UPDATE records SET data_json=? WHERE id=?",(json.dumps(data),cur.lastrowid))
        return data,201
    if not item_id: raise HTTPException(400,"This method requires an {id} path parameter")
    row=c.execute("SELECT id,data_json FROM records WHERE project_id=? AND resource=? AND json_extract(data_json,'$.id')=?",
                  (project["id"],resource,str(item_id))).fetchone()
    if not row and str(item_id).isdigit():
        row=c.execute("SELECT id,data_json FROM records WHERE project_id=? AND resource=? AND id=?",
                      (project["id"],resource,int(item_id))).fetchone()
    if not row: raise HTTPException(404,"Record not found")
    data=json.loads(row["data_json"])
    if request.method in {"PUT","PATCH"}:
        if not isinstance(body,dict): raise HTTPException(422,"JSON object body required")
        data = body if request.method=="PUT" else {**data,**body}
        c.execute("UPDATE records SET data_json=?,updated_at=? WHERE id=?",(json.dumps(data),time.time(),row["id"]))
        return data,200
    if request.method=="DELETE":
        c.execute("DELETE FROM records WHERE id=?",(row["id"],))
        return {"deleted":True},200
    raise HTTPException(405,"Method not supported")

@app.api_route("/runtime/{slug}/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE"])
async def runtime(slug: str, path: str, request: Request, x_api_key: str | None = Header(default=None)):
    started=time.perf_counter()
    actual="/"+path
    try:
        with db() as c:
            project=get_project(c,slug)
            if project["api_key_hash"]:
                supplied=hashlib.sha256((x_api_key or "").encode()).hexdigest()
                if not secrets.compare_digest(supplied,project["api_key_hash"]):
                    raise HTTPException(401,"A valid X-API-Key header is required")
            candidates=c.execute("SELECT * FROM endpoints WHERE project_id=? AND method=? ORDER BY id",
                                 (project["id"],request.method)).fetchall()
            match=None; params={}
            for ep in candidates:
                found=route_match(ep["path"],actual)
                if found is not None: match=ep; params=found; break
            if not match:
                raise HTTPException(404,"No endpoint matches this method and path")
            try: body=await request.json() if request.method in {"POST","PUT","PATCH"} else None
            except Exception: body=None
            if match["handler"]=="crud":
                data,status=execute_crud(c,project,match,params,request,body)
            else:
                data=json.loads(match["response_json"]); status=match["status_code"]
            result={"data":data,"status":status}
            elapsed=(time.perf_counter()-started)*1000
            c.execute("INSERT INTO history(project_id,method,path,status,duration_ms,response_json,created_at) VALUES(?,?,?,?,?,?,?)",
                      (project["id"],request.method,actual,status,elapsed,json.dumps(data),time.time()))
        return JSONResponse(content=result["data"],status_code=result["status"])
    except HTTPException as exc:
        return JSONResponse({"detail":exc.detail},status_code=exc.status_code)

@app.get("/api/projects/{slug}/history")
def get_history(slug: str):
    with db() as c:
        p=get_project(c,slug)
        rows=c.execute("SELECT * FROM history WHERE project_id=? ORDER BY id DESC LIMIT 50",(p["id"],)).fetchall()
        return [dict(r) for r in rows]

@app.get("/api/health")
def health():
    return {"ok":True,"service":"API Creator Studio"}
