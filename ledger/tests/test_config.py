from app.config import Settings, get_settings


def test_settings_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    s = Settings()
    assert "sqlite" in s.database_url
    assert s.http_user_agent.startswith("benchmark-ledger")
    get_settings.cache_clear()


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/x.db")
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "12")
    get_settings.cache_clear()
    s = get_settings()
    assert s.database_url.endswith("x.db")
    assert s.http_timeout_seconds == 12.0
    get_settings.cache_clear()
