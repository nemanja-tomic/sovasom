from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str = Field(default="", repr=False)
    database_password: SecretStr | None = Field(default=None, repr=False)
    database_password_file: Path | None = Field(default=None, repr=False)
    database_host: str = "db"
    public_origin: str = "https://testserver"

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        def literal_dotenv():
            # Treat secrets literally, matching single-quoted Compose .env values.
            path = dotenv_settings.env_file
            if not path or not Path(path).is_file():
                return {}
            return {
                key.lower(): value
                for key, value in dotenv_values(path, interpolate=False).items()
                if value is not None
            }

        return init_settings, env_settings, literal_dotenv

    @model_validator(mode="after")
    def connection_url(self):
        if self.database_password_file:
            try:
                self.database_password = SecretStr(
                    self.database_password_file.read_text().rstrip("\n")
                )
            except OSError:
                raise ValueError("Cannot read DATABASE_PASSWORD_FILE") from None
        if not self.database_url:
            if not self.database_password or not self.database_password.get_secret_value():
                raise ValueError("Set DATABASE_PASSWORD or DATABASE_URL")
            self.database_url = URL.create(
                "postgresql+psycopg",
                username="office",
                password=self.database_password.get_secret_value(),
                host=self.database_host,
                database="office",
            ).render_as_string(hide_password=False)
        return self

    @field_validator("public_origin")
    @classmethod
    def https_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path:
            raise ValueError("PUBLIC_ORIGIN must be an HTTPS origin without a path")
        return value
