"""Рекомендации по одежде. Ориентир: «ощущается как»"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import WeatherCfg
from .weather import Hour

RAIN_CODES = set(range(51, 58)) | set(range(61, 68)) | {80, 81, 82}
SNOW_CODES = set(range(71, 78)) | {85, 86}
THUNDER_CODES = {95, 96, 99}
FREEZING_CODES = {56, 57, 66, 67}

# (порог «ощущается как», слои); берётся первая строка, где feels >= порог
LAYERS: list[tuple[float, str]] = [
    (25, "футболка и лёгкие брюки или шорты"),
    (18, "футболка, сверху тонкая кофта или рубашка"),
    (12, "лонгслив или худи, сверху лёгкая куртка или ветровка"),
    (6, "свитер или толстовка, сверху демисезонная куртка"),
    (0, "тёплый свитер или флис, сверху тёплая куртка"),
    (-10, "термослой, свитер, зимняя куртка"),
    (-20, "термобельё, флис или свитер, пуховик"),
    (-999, "термобельё, тёплый свитер, пуховик, под брюки тёплый слой"),
]


@dataclass
class Advice:
    layers: str
    shoes: str
    accessories: list[str] = field(default_factory=list)  # шапка, шарф, перчатки, зонт
    warnings: list[str] = field(default_factory=list)


def precip_kind(h: Hour) -> str | None:
    """'дождь' | 'снег' | 'гроза' | None"""
    if h.code in THUNDER_CODES:
        return "гроза"
    if h.code in SNOW_CODES:
        return "снег"
    if h.code in RAIN_CODES:
        return "дождь"
    if h.precip >= 0.1:
        return "снег" if h.temp <= 0 else "дождь"
    return None


def recommend(points: list[Hour], cfg: WeatherCfg) -> Advice:
    """Одна рекомендация на несколько моментов дня (выход, конец пар): по худшему из них."""
    min_feels = min(p.feels for p in points)
    max_feels = max(p.feels for p in points)
    max_wind = max(p.wind for p in points)
    max_gust = max(p.gust for p in points)
    kinds = {k for p in points if (k := precip_kind(p))}
    wet = bool(kinds)
    rain = bool(kinds & {"дождь", "гроза"})
    windy = max_wind >= 7

    layers = next(text for thr, text in LAYERS if min_feels >= thr)
    if max_feels - min_feels >= 6:
        layers += "; днём теплее, лучше слоями"

    # Обувь
    if min_feels >= 12:
        shoes = "непромокаемые кроссовки или ботинки" if wet else "кроссовки"
    elif min_feels >= 0:
        shoes = "непромокаемые ботинки" if wet else "закрытая обувь"
    elif min_feels >= -15:
        shoes = "зимние ботинки" + (", непромокаемые" if wet else "")
    else:
        shoes = "тёплые зимние ботинки и тёплые носки"

    # Аксессуары
    acc: list[str] = []
    if min_feels <= 0 or (windy and min_feels <= 4):
        acc.append("шапка")
    if min_feels <= 2 or (windy and min_feels <= 7):
        acc.append("шарф")
    if min_feels <= -3 or (windy and min_feels <= 2):
        acc.append("варежки" if min_feels <= -15 else "перчатки")
    strong_wind = max_wind >= cfg.strong_wind_ms or max_gust >= cfg.strong_gust_ms
    if rain and not strong_wind:
        acc.append("зонт")

    # Предупреждения
    warn: list[str] = []
    if "гроза" in kinds:
        warn.append("гроза, по возможности переждите в помещении")
    if strong_wind:
        warn.append(f"сильный ветер, порывы до {max_gust:.0f} м/с")
    if any(p.code in FREEZING_CODES for p in points) or any(
        -3 <= p.temp <= 1 and precip_kind(p) for p in points
    ):
        warn.append("возможен гололёд, идите аккуратно")
    if max_feels >= 30:
        warn.append("жара, возьмите воду и головной убор")
    if min_feels <= -25:
        warn.append("сильный мороз, закрывайте лицо шарфом")
    return Advice(layers=layers, shoes=shoes, accessories=acc, warnings=warn)
