import pytest
from office.config import Settings
from sqlalchemy.engine import make_url


def test_env_file_builds_database_connection_without_corrupting_password(tmp_path, monkeypatch):
    for key in ["DATABASE_URL", "DATABASE_PASSWORD", "PUBLIC_ORIGIN"]:
        monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text(
        "DATABASE_PASSWORD='synthetic:p@ss/$word#${UNCHANGED}'\n"
        "PUBLIC_ORIGIN=https://localhost:8443\n"
        "INITIAL_PASSWORD='not an application setting'\n"
    )
    settings = Settings(_env_file=path)
    url = make_url(settings.database_url)
    assert url.password == "synthetic:p@ss/$word#${UNCHANGED}"
    assert (url.host, url.username, url.database) == ("db", "office", "office")
    assert settings.public_origin == "https://localhost:8443"
    assert "synthetic" not in repr(settings)


def test_process_environment_overrides_dotenv_values(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_PASSWORD", "environment:p@ss/$#")
    path = tmp_path / ".env"
    path.write_text("DATABASE_PASSWORD='file password'\n")
    assert make_url(Settings(_env_file=path).database_url).password == "environment:p@ss/$#"


def test_invalid_configuration_does_not_echo_bootstrap_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    path = tmp_path / ".env"
    path.write_text("DATABASE_PASSWORD=''\nINITIAL_PASSWORD='synthetic secret never logged'\n")
    with pytest.raises(ValueError) as error:
        Settings(_env_file=path)
    assert "synthetic secret never logged" not in str(error.value)


def test_database_password_can_be_read_from_explicit_secret_file(tmp_path, monkeypatch):
    from office.config import Settings

    secret = tmp_path / "password"
    secret.write_text("synthetic-file-password")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    monkeypatch.setenv("DATABASE_PASSWORD_FILE", str(secret))
    settings = Settings(_env_file=None)
    assert "synthetic-file-password" in settings.database_url
    assert "synthetic-file-password" not in repr(settings)
