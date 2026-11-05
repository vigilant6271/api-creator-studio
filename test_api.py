import json
from fastapi.testclient import TestClient
from app.main import app, route_match, validate_path

client = TestClient(app)

def test_route_match():
    assert route_match("/users/{id}", "/users/42") == {"id":"42"}
    assert route_match("/users/{id}", "/posts/42") is None

def test_starter_api_list():
    r=client.get("/runtime/starter-api/users")
    assert r.status_code==200
    assert isinstance(r.json(),list)
    assert len(r.json())>=2

def test_starter_api_get_one():
    r=client.get("/runtime/starter-api/users/1")
    assert r.status_code==200
    assert r.json()["name"]=="Ada Lovelace"

def test_starter_api_create():
    r=client.post("/runtime/starter-api/users",json={"name":"Test User","email":"test@example.com"})
    assert r.status_code==201
    assert r.json()["name"]=="Test User"

def test_openapi():
    spec=client.get("/api/projects/starter-api/openapi.json").json()
    assert spec["openapi"]=="3.1.0"
    assert "/users" in spec["paths"]

def test_invalid_path():
    try:
        validate_path("users")
        assert False
    except Exception:
        assert True
