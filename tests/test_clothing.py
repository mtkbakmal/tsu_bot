from datetime import datetime
from zoneinfo import ZoneInfo

from tsu_bot.clothing import recommend
from tsu_bot.config import WeatherCfg
from tsu_bot.weather import Hour

TZ = ZoneInfo("Asia/Tomsk")
CFG = WeatherCfg()


def H(feels, temp=None, precip=0.0, wind=2.0, gust=4.0, code=0):
    return Hour(datetime(2026, 10, 1, 8, tzinfo=TZ), temp if temp is not None else feels, feels, precip, wind, gust, code)


def test_warm_dry():
    a = recommend([H(24)], CFG)
    assert a.shoes == "кроссовки" and a.accessories == [] and a.warnings == []


def test_deep_frost_full_kit():
    a = recommend([H(-27, wind=3)], CFG)
    assert {"шапка", "шарф", "варежки"} <= set(a.accessories)
    assert "зимние ботинки" in a.shoes
    assert any("мороз" in w for w in a.warnings)


def test_cold_uses_worst_moment():
    a = recommend([H(3), H(-5)], CFG)  # выход +3, конец пар -5
    assert "перчатки" in a.accessories and "термослой" in a.layers


def test_rain_umbrella_and_waterproof_shoes():
    a = recommend([H(9, precip=1.2, code=61)], CFG)
    assert "зонт" in a.accessories and a.shoes.startswith("непромокаемые")


def test_strong_wind_no_umbrella_warns():
    a = recommend([H(8, precip=1.0, code=63, wind=11, gust=18)], CFG)
    assert "зонт" not in a.accessories
    assert any("ветер" in w for w in a.warnings)


def test_ice_warning_and_thunder():
    assert any("гололёд" in w for w in recommend([H(-1, temp=-1, precip=0.5, code=71)], CFG).warnings)
    assert any("гроза" in w for w in recommend([H(18, code=95, precip=2)], CFG).warnings)


def test_wind_adds_hat_and_scarf_at_mild_temp():
    a = recommend([H(4, wind=8)], CFG)
    assert "шапка" in a.accessories and "шарф" in a.accessories
