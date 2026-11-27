def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_cors_allows_configured_origin(client):
    r = client.options("/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unknown_origin(client):
    r = client.options("/health", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers



def test_cors_origins_parsing():
    from app.config import DEFAULT_CORS_ORIGINS, Settings

    base = {"DATABASE_URL": "sqlite://", "SECRET_KEY": "x", "ENCRYPTION_KEY": "x", "OPENAI_API_KEY": "x"}
    assert Settings(**base, CORS_ORIGINS="").cors_origins == list(DEFAULT_CORS_ORIGINS)
    assert Settings(**base, CORS_ORIGINS="  ").cors_origins == list(DEFAULT_CORS_ORIGINS)
    assert Settings(**base, CORS_ORIGINS="https://a.example, https://b.example").cors_origins == [
        "https://a.example", "https://b.example"]


def test_unauthenticated_test_routes_are_gone(client):
    """인증 없이 열려 있던 테스트용 주소는 없다."""
    assert client.get("/api/test/hello").status_code == 404
    assert client.post("/api/test/echo", params={"text": "x"}).status_code == 404

