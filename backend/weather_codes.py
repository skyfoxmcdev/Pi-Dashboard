"""WMO weather-code translation shared by the API payload."""

from __future__ import annotations

WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Ciel dégagé", "clear"),
    1: ("Plutôt dégagé", "partly"),
    2: ("Partiellement nuageux", "partly"),
    3: ("Couvert", "cloudy"),
    45: ("Brouillard", "fog"),
    48: ("Brouillard givrant", "fog"),
    51: ("Bruine légère", "drizzle"),
    53: ("Bruine modérée", "drizzle"),
    55: ("Bruine dense", "drizzle"),
    56: ("Bruine verglaçante légère", "sleet"),
    57: ("Bruine verglaçante dense", "sleet"),
    61: ("Pluie faible", "rain"),
    63: ("Pluie modérée", "rain"),
    65: ("Pluie forte", "rain"),
    66: ("Pluie verglaçante légère", "sleet"),
    67: ("Pluie verglaçante forte", "sleet"),
    71: ("Neige faible", "snow"),
    73: ("Neige modérée", "snow"),
    75: ("Neige forte", "snow"),
    77: ("Grains de neige", "snow"),
    80: ("Averses faibles", "rain"),
    81: ("Averses modérées", "rain"),
    82: ("Averses violentes", "rain"),
    85: ("Averses de neige faibles", "snow"),
    86: ("Averses de neige fortes", "snow"),
    95: ("Orage", "thunder"),
    96: ("Orage avec grêle", "thunder"),
    99: ("Orage avec forte grêle", "thunder"),
}

DIRECTION_LABELS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSO",
    "SO",
    "OSO",
    "O",
    "ONO",
    "NO",
    "NNO",
]


def describe_weather(code: int | None, is_day: bool = True) -> tuple[str, str]:
    """Return a French label and a frontend icon key for a WMO code."""

    if code is None:
        return "Conditions inconnues", "unknown"
    label, icon = WEATHER_CODES.get(int(code), ("Conditions inconnues", "unknown"))
    if icon == "clear":
        return label, "clear-day" if is_day else "clear-night"
    if icon == "partly":
        return label, "partly-day" if is_day else "partly-night"
    return label, icon


def wind_direction_label(degrees: float | int | None) -> str | None:
    """Convert meteorological degrees (0 = north) to a French cardinal point."""

    if degrees is None:
        return None
    try:
        value = float(degrees)
    except (TypeError, ValueError):
        return None
    index = int((value % 360) / 22.5 + 0.5) % 16
    return DIRECTION_LABELS[index]
