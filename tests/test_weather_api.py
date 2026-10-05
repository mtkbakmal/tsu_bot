from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

import tsu_bot.weather as weather_mod
from tsu_bot.config import WeatherCfg
from tsu_bot.weather import WeatherClient, WeatherError, nearest_hour

TZ = ZoneInfo("Asia/Tomsk")


def _open_meteo_payload():
    times = [f"2026-10-01T{h:02d}:00" for h in range(24)]
    n = len(times)
    return {"hourly": {
        "time": times,
        "temperature_2m": [-5.0] * 7 + [None] + [-4.0] * (n - 8),   # None: пропуск в данных
        "apparent_temperature": [-10.0] * 7 + [None] + [-9.0] * (n - 8),
        "precipitation": [0.0] * n,
        "wind_speed_10m": [4.0] * n,
        "wind_gusts_10m": [8.0] * n,
        "weather_code": [3] * n,
    }}


async def test_open_meteo_parsing(monkeypatch):
    real = httpx.AsyncClient
    captured = {}

    def handler(request: httpx.Request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_open_meteo_payload())

    monkeypatch.setattr(weather_mod.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    wx = WeatherClient(WeatherCfg(), TZ)
    out = await wx.at([datetime(2026, 10, 1, 8, 12, tzinfo=TZ), datetime(2026, 10, 1, 16, 20, tzinfo=TZ)])
    assert captured["params"]["timezone"] == "Asia/Tomsk" and captured["params"]["wind_speed_unit"] == "ms"
    assert out[0].time.hour == 8 and out[0].feels == -9.0     # 08:12 -> час 08:00 (07:00 был бы None)
    assert out[1].time.hour == 16 and out[1].wind == 4.0      # 16:20 -> 16:00


async def test_weather_http_error_is_weather_error(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(weather_mod.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    try:
        await WeatherClient(WeatherCfg(), TZ).at([datetime(2026, 10, 1, 8, tzinfo=TZ)])
    except WeatherError:
        return
    raise AssertionError("ожидался WeatherError")


def test_nearest_hour_rounding():
    assert nearest_hour(datetime(2026, 10, 1, 8, 29, tzinfo=TZ)).hour == 8
    assert nearest_hour(datetime(2026, 10, 1, 8, 30, tzinfo=TZ)).hour == 9
