def test_register(client):
    resp = client.post("/api/auth/register", json={
        "username": "tester1",
        "password": "testpass123",
    })
    assert resp.status_code == 201
    assert resp.json()["username"] == "tester1"


def test_register_duplicate(client):
    client.post("/api/auth/register", json={
        "username": "tester2",
        "password": "testpass123",
    })
    resp = client.post("/api/auth/register", json={
        "username": "tester2",
        "password": "testpass123",
    })
    assert resp.status_code == 400


def test_login_success(client):
    client.post("/api/auth/register", json={
        "username": "tester3",
        "password": "testpass123",
    })
    resp = client.post("/api/auth/login", json={
        "username": "tester3",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={
        "username": "tester4",
        "password": "testpass123",
    })
    resp = client.post("/api/auth/login", json={
        "username": "tester4",
        "password": "wrongpass",
    })
    assert resp.status_code == 401


def test_me_without_token(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 403


def test_me_with_token(client):
    client.post("/api/auth/register", json={
        "username": "tester5",
        "password": "testpass123",
    })
    resp = client.post("/api/auth/login", json={
        "username": "tester5",
        "password": "testpass123",
    })
    token = resp.json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "tester5"


def test_password_too_short(client):
    resp = client.post("/api/auth/register", json={
        "username": "tester6",
        "password": "12345",
    })
    assert resp.status_code == 422


def test_username_too_short(client):
    resp = client.post("/api/auth/register", json={
        "username": "a",
        "password": "123456",
    })
    assert resp.status_code == 422
