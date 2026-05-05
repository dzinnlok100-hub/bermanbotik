"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Loaded from `.env` file or environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    telegram_bot_token: str = Field(
        ...,
        description="Telegram bot token from @BotFather",
        validation_alias="TELEGRAM_BOT_TOKEN",
    )

    admin_user_ids_raw: str = Field(
        default="",
        validation_alias="ADMIN_USER_IDS",
    )

    db_path: Path = Field(default=Path("data/bot.db"), validation_alias="DB_PATH")
    images_dir: Path = Field(default=Path("data/images"), validation_alias="IMAGES_DIR")

    source_base_url: str = Field(
        default="https://amkbook.net",
        validation_alias="SOURCE_BASE_URL",
    )
    source_book_id: int = Field(default=1, validation_alias="SOURCE_BOOK_ID")

    @property
    def admin_user_ids(self) -> set[int]:
        """Parse comma-separated admin IDs."""
        if not self.admin_user_ids_raw.strip():
            return set()
        return {
            int(x.strip())
            for x in self.admin_user_ids_raw.split(",")
            if x.strip().lstrip("-").isdigit()
        }


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
