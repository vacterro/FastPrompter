"""One real, key-free weather provider for ambience rules (T-1238-C3.11).

Open-Meteo needs no API key and no account.  It is used ONLY for a location
the user typed in and only after an explicit opt-in: FastPrompter never
geolocates anyone, never reads the OS location service, and sends nothing
but the coordinates the user configured.

The network call lives here, off the UI thread by contract: this module is
pure request/parse with a hard timeout and no retries beyond one, and the
runtime controller owns the schedule.  A failure returns ``None`` -- never a
guessed condition, because the ambience engine treats "unknown" and "clear"
very differently.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from fastprompter.core.ambience_engine import WeatherProvider

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_S = 8.0
USER_AGENT = "FastPrompter/ambience (+https://github.com/vacterro/FastPrompter)"

#: WMO weather interpretation codes -> the six conditions the engine knows.
#: https://open-meteo.com/en/docs (weather_code table)
_WMO_CONDITIONS: dict[int, str] = {}


def _fill(codes, condition: str) -> None:
    for code in codes:
        _WMO_CONDITIONS[code] = condition


_fill((0, 1), "clear")
_fill((2, 3, 45, 48), "cloudy")
_fill((51, 53, 55, 56, 57), "drizzle")
_fill((61, 63, 65, 66, 67, 80, 81, 82), "rain")
_fill((71, 73, 75, 77, 85, 86), "snow")
_fill((95, 96, 99), "thunderstorm")


def condition_for_code(code) -> str | None:
    """Map one WMO code to a known condition, or None when unrecognised."""
    try:
        return _WMO_CONDITIONS.get(int(code))
    except (TypeError, ValueError):
        return None


def parse_response(payload: dict) -> str | None:
    """Extract the current condition from an Open-Meteo response body."""
    if not isinstance(payload, dict):
        return None
    current = payload.get("current") or payload.get("current_weather") or {}
    if not isinstance(current, dict):
        return None
    for key in ("weather_code", "weathercode"):
        if key in current:
            return condition_for_code(current[key])
    return None


def build_url(latitude: float, longitude: float) -> str:
    query = urllib.parse.urlencode({
        "latitude": f"{float(latitude):.4f}",
        "longitude": f"{float(longitude):.4f}",
        "current": "weather_code",
        "timezone": "auto",
    })
    return f"{OPEN_METEO_URL}?{query}"


class OpenMeteoWeatherProvider(WeatherProvider):
    """Key-free current-conditions provider for one configured location."""

    def __init__(self, latitude: float, longitude: float, *,
                 opener=None, timeout: float = REQUEST_TIMEOUT_S) -> None:
        self.latitude = float(latitude)
        self.longitude = float(longitude)
        self._opener = opener or urllib.request.urlopen
        self._timeout = float(timeout)
        self.last_error: str = ""

    def fetch(self) -> str | None:
        """One bounded request.  Any failure is None, never a guess."""
        request = urllib.request.Request(
            build_url(self.latitude, self.longitude),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(64 * 1024)
            payload = json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError,
                UnicodeDecodeError) as exc:
            self.last_error = str(exc)
            return None
        self.last_error = ""
        return parse_response(payload)


def provider_for(config: dict, *, opener=None) -> WeatherProvider | None:
    """Build a provider from a persisted weather config, or None.

    Returns None whenever weather is not opted in or the location is not
    usable -- the caller must then leave the weather trigger inert rather
    than inventing a condition.
    """
    if not (config or {}).get("enabled"):
        return None
    latitude = config.get("latitude")
    longitude = config.get("longitude")
    if latitude is None or longitude is None:
        return None
    return OpenMeteoWeatherProvider(latitude, longitude, opener=opener)
