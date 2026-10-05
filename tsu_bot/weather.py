"""Клиент Open-Meteo (бесплатно, без ключа)."""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .config import WeatherCfg

log = logging.getLogger(__name__)

URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = (
    "temperature_2m,apparent_temperature,precipitation,"
    "wind_speed_10m,wind_gusts_10m,weather_code"
)


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class Hour:
    time: datetime
    temp: float
    feels: float
    precip: float  # мм за час
    wind: float  # м/с
    gust: float  # м/с
    code: int  # WMO weather code


def nearest_hour(dt: datetime) -> datetime:
    base = dt.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=1) if dt.minute >= 30 else base


class WeatherClient:
    def __init__(self, cfg: WeatherCfg, tz: ZoneInfo) -> None:
        self.cfg = cfg
        self.tz = tz
        self._cache: dict[datetime, Hour] = {}
        self._cached_at = 0.0

    async def _load(self) -> dict[datetime, Hour]:
        params = {
            "latitude": self.cfg.latitude,
            "longitude": self.cfg.longitude,
            "hourly": HOURLY,
            "wind_speed_unit": "ms",
            "timezone": self.tz.key,
            "forecast_days": 3,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(URL, params=params)
                r.raise_for_status()
            h = r.json()["hourly"]
            out: dict[datetime, Hour] = {}
            for i, t in enumerate(h["time"]):
                if h["temperature_2m"][i] is None or h["apparent_temperature"][i] is None:
                    continue
                when = datetime.fromisoformat(t).replace(tzinfo=self.tz)
                out[when] = Hour(
                    time=when,
                    temp=h["temperature_2m"][i],
                    feels=h["apparent_temperature"][i],
                    precip=h["precipitation"][i] or 0.0,
                    wind=h["wind_speed_10m"][i] or 0.0,
                    gust=h["wind_gusts_10m"][i] or 0.0,
                    code=int(h["weather_code"][i] or 0),
                )
            return out
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
            raise WeatherError(f"Open-Meteo: {e}") from e

    async def at(self, moments: list[datetime]) -> list[Hour]:
        """Погода на ближайший час к каждому моменту (пропуская те, для которых прогноза нет)."""
        if not self._cache or _time.monotonic() - self._cached_at > self.cfg.cache_minutes * 60:
            self._cache = await self._load()
            self._cached_at = _time.monotonic()
        out = []
        for m in moments:
            hour = self._cache.get(nearest_hour(m.astimezone(self.tz)))
            if hour is None:
                raise WeatherError(f"Нет прогноза на {m:%d.%m %H:%M}")
            out.append(hour)
        return out
