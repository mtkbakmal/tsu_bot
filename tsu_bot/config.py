"""Настройки: секреты из переменных окружения/.env, остальное из config.yaml."""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(BaseSettings):
    """Секреты и окружение. Читаются из переменных окружения, а при наличии и из .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_owner_id: int
    database_url: str
    config_path: str = "config.yaml"
    log_level: str = "INFO"


class ScheduleCfg(BaseModel):
    source: Literal["ics", "api"] = "ics"
    ics_source: str = "data/schedule.ics"  # путь к файлу или http(s)-ссылка
    api_base_url: str = "https://intime.tsu.ru/api/web/v1"
    api_url_template: str = (
        "{base}/schedule/group?id={group_id}&dateFrom={date_from}&dateTo={date_to}"
    )
    faculty_id: str = ""
    group_id: str = ""
    group_name: str = "932603"
    subgroup: str = "б"
    timezone: str = "Asia/Tomsk"
    refresh_minutes: int = Field(30, ge=5)
    days_ahead: int = Field(7, ge=2)


class CommuteCfg(BaseModel):
    walk_to_stop_min: int = 5
    bus_wait_min: int = 3
    bus_ride_min: int = 15
    # Пешком от главных ворот до корпуса: {номер корпуса: минуты}
    walk_from_gate_min: dict[int, int] = {2: 5}
    default_walk_from_gate_min: int = 10
    safety_margin_min: int = 5
    shower_min: int = 10
    eating_min: int = 5
    wake_extra_min: int = 15  # проснуться, одеться, собраться


class NotifyCfg(BaseModel):
    morning_minutes_before_first_lesson: int = 60
    leave_reminders_min: list[int] = [15]
    evening_time: str = "21:00"
    evening_send_when_no_lessons: bool = True
    tasks_retention_days: int = 7

    @property
    def evening_clock(self) -> time:
        h, m = self.evening_time.split(":")
        return time(int(h), int(m))


class WeatherCfg(BaseModel):
    latitude: float = 56.4885
    longitude: float = 84.9480
    cache_minutes: int = 20
    strong_wind_ms: float = 10.0
    strong_gust_ms: float = 15.0


class Settings(BaseModel):
    env: Env
    schedule: ScheduleCfg
    commute: CommuteCfg
    notify: NotifyCfg
    weather: WeatherCfg


def load_settings() -> Settings:
    env = Env()  # type: ignore[call-arg]
    path = Path(env.config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Не найден {path}. Скопируйте config.example.yaml в config.yaml."
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings(
        env=env,
        schedule=ScheduleCfg(**raw.get("schedule", {})),
        commute=CommuteCfg(**raw.get("commute", {})),
        notify=NotifyCfg(**raw.get("notify", {})),
        weather=WeatherCfg(**raw.get("weather", {})),
    )
