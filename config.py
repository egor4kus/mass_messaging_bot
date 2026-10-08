from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"В .env не задана обязательная переменная {name}")
    return value


def _admin_usernames(value: str) -> frozenset[str]:
    usernames = frozenset(
        item.strip().lstrip("@").lower() for item in value.split(",") if item.strip()
    )
    if not usernames:
        raise RuntimeError("ADMIN_USERNAMES должен содержать хотя бы один @username")
    return usernames


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_usernames: frozenset[str]
    db_path: Path
    defaults: dict[str, str]


def load_settings() -> Settings:
    # Docker Compose передаёт переменные в контейнер, локально берём их из .env.
    load_dotenv()
    return Settings(
        bot_token=_required("BOT_TOKEN"),
        admin_usernames=_admin_usernames(_required("ADMIN_USERNAMES")),
        db_path=Path(os.getenv("DB_PATH", "data/bot.db")),
        defaults={
            "welcome": _required("WELCOME_MESSAGE"),
            "button_1_text": _required("BUTTON_1_TEXT"),
            "answer_1": _required("ANSWER_1_MESSAGE"),
            "button_2_text": _required("BUTTON_2_TEXT"),
            "answer_2": _required("ANSWER_2_MESSAGE"),
        },
    )

