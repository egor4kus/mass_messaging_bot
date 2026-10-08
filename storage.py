from __future__ import annotations

import sqlite3
from pathlib import Path


class Storage:
    def __init__(self, db_path: Path, defaults: dict[str, str]) -> None:
        self.db_path = db_path
        self.defaults = defaults

    def initialize(self, admin_usernames: frozenset[str]) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    setting_key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            for key, value in self.defaults.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings (setting_key, value) VALUES (?, ?)",
                    (key, value),
                )
        self.sync_admin_rights(admin_usernames)

    def sync_admin_rights(self, admin_usernames: frozenset[str]) -> None:
        """Конфиг — источник прав; флаг в БД обновляется при каждом запуске."""
        with self._connect() as connection:
            connection.execute("UPDATE users SET is_admin = 0")
            placeholders = ", ".join("?" for _ in admin_usernames)
            connection.execute(
                f"UPDATE users SET is_admin = 1 WHERE lower(username) IN ({placeholders})",
                tuple(admin_usernames),
            )

    def register_started_user(self, telegram_id: int, username: str | None, is_admin: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (telegram_id, username, is_admin)
                VALUES (?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    is_admin = excluded.is_admin
                """,
                (telegram_id, username.lower() if username else None, int(is_admin)),
            )

    def refresh_known_user_role(
        self, telegram_id: int, username: str | None, is_admin: bool
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET username = ?, is_admin = ? WHERE telegram_id = ?",
                (username.lower() if username else None, int(is_admin), telegram_id),
            )

    def get(self, key: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE setting_key = ?", (key,)
            ).fetchone()
        return row[0] if row else self.defaults[key]

    def set(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (setting_key, value) VALUES (?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def user_ids(self) -> list[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT telegram_id FROM users").fetchall()
        return [row[0] for row in rows]

    def user_count(self) -> int:
        with self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

