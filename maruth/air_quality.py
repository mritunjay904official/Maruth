"""Regional presets, Open-Meteo bridge around weather_api.py, inversion analysis, and TTL caching."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Optional
import httpx

from weather_api import get_live_air_quality
from maruth.schemas import AirQualityReport, CityPreset, HourlyWindowPoint

CITY_PRESETS: dict[str, CityPreset] = {
    "bolpur": CityPreset(
        id="bolpur",
        name="Bolpur (Santiniketan)",
        region="West Bengal, India",
        lat=23.67,
        lon=87.68,
        climate_note="Calm winter nights trap rice-stubble smoke, biomass cooking, and brick-kiln plumes over Birbhum.",
        baseline_pm25=96.0,
        baseline_pm10=148.0,
        baseline_co=680.0,
        baseline_no2=28.0,
    ),
    "kolkata": CityPreset(
        id="kolkata",
        name="Kolkata",
        region="West Bengal, India",
        lat=22.5726,
        lon=88.3639,
        climate_note="High winter humidity + Gangetic boundary-layer inversion traps diesel traffic, road dust, and coal smoke.",
        baseline_pm25=142.0,
        baseline_pm10=218.0,
        baseline_co=1050.0,
        baseline_no2=56.0,
    ),
    "delhi_ncr": CityPreset(
        id="delhi_ncr",
        name="Delhi NCR",
        region="National Capital Region, India",
        lat=28.6139,
        lon=77.2090,
        climate_note="Severe Indo-Gangetic thermal inversion locks vehicular NOx, crop-residue smoke, and winter heating fumes near ground.",
        baseline_pm25=268.0,
        baseline_pm10=385.0,
        baseline_co=1720.0,
        baseline_no2=82.0,
    ),
    "patna": CityPreset(
        id="patna",
        name="Patna",
        region="Bihar, India",
        lat=25.5941,
        lon=85.1376,
        climate_note="Riverine moisture and stagnant winter winds concentrate resuspended dust and solid-fuel emissions.",
        baseline_pm25=215.0,
        baseline_pm10=320.0,
        baseline_co=1390.0,
        baseline_no2=62.0,
    ),
    "lahore": CityPreset(
        id="lahore",
        name="Lahore",
        region="Punjab, Pakistan",
        lat=31.5204,
        lon=74.3587,
        climate_note="Shallow winter inversion lid traps dense traffic exhaust, industrial plumes, and regional agricultural haze.",
        baseline_pm25=255.0,
        baseline_pm10=360.0,
        baseline_co=1640.0,
        baseline_no2=74.0,
    ),
    "beijing": CityPreset(
        id="beijing",
        name="Beijing",
        region="North China Plain",
        lat=39.9042,
        lon=116.4074,
        climate_note="Mountain-rimmed basin slows winter dispersion during calm high-pressure episodes.",
        baseline_pm25=88.0,
        baseline_pm10=125.0,
        baseline_co=790.0,
        baseline_no2=46.0,
    ),
    "salt_lake_city": CityPreset(
        id="salt_lake_city",
        name="Salt Lake City",
        region="Utah, USA",
        lat=40.7608,
        lon=-111.8910,
        climate_note="Cold-air pools in the Wasatch valley create classic multi-day winter PM2.5 inversions.",
        baseline_pm25=48.0,
        baseline_pm10=68.0,
        baseline_co=490.0,
        baseline_no2=39.0,
    ),
}

_AQI_CACHE: dict[str, tuple[float, AirQualityReport]] = {}
AQI_CACHE_TTL_SECONDS = 900  # 15 minutes


def pm25_to_us_aqi(pm25: float) -> tuple[int, str, str]:
    """Compute US EPA AQI from PM2.5 (ug/m3) using official piecewise breakpoints."""
    c = max(0.0, math.floor(pm25 * 10.0) / 10.0)
    breakpoints = [
        (0.0, 9.0, 0, 50, "Good", "#10b981"),
        (9.1, 35.4, 51, 100, "Moderate", "#eab308"),
        (35.5, 55.4, 101, 150, "Unhealthy for Sensitive Groups", "#f97316"),
        (55.5, 125.4, 151, 200, "Unhealthy", "#ef4444"),
        (125.5, 225.4, 201, 300, "Very Unhealthy", "#a855f7"),
        (225.5, 500.4, 301, 500, "Hazardous", "#be123c"),
    ]
    for c_low, c_high, i_low, i_high, label, color in breakpoints:
        if c <= c_high:
            aqi = round(((i_high - i_low) / (c_high - c_low)) * (c - c_low) + i_low)
            return aqi, label, color
    return 500, "Hazardous", "#be123c"


def assess_inversion_risk(pm25: float, wind_kmh: Optional[float], temp_c: Optional[float]) -> tuple[str, str]:
    """Classify winter boundary-layer trapping risk from wind speed, temperature, and PM2.5."""
    wind = wind_kmh if wind_kmh is not None else 6.0
    temp = temp_c if temp_c is not None else 16.0

    if pm25 >= 180 or (wind < 5.0 and pm25 >= 90):
        return (
            "SEVERE",
            f"Calm air ({wind:.1f} km/h) at {temp:.1f}°C traps pollutants under a shallow winter inversion lid—avoid morning/late-evening outdoor exertion.",
        )
    if pm25 >= 90 or (wind < 8.0 and temp < 18.0):
        return (
            "HIGH",
            f"Light winds ({wind:.1f} km/h) slow vertical mixing; smoke and traffic NO2 accumulate near street level after sunset.",
        )
    if pm25 >= 45 or wind < 12.0:
        return (
            "MODERATE",
            f"Moderate dispersion ({wind:.1f} km/h). Mid-afternoon sunlight provides the cleanest brief ventilation window.",
        )
    return (
        "LOW",
        f"Active breeze ({wind:.1f} km/h) is dispersing surface emissions; short cross-ventilation windows are favorable.",
    )


def _synthesize_hourly_profile(base_pm25: float, base_wind: float, base_temp: float) -> list[HourlyWindowPoint]:
    """Generate a physically realistic diurnal winter smog curve when live hourly data is unavailable."""
    # Typical winter smog diurnal multipliers: morning & late-evening inversion peaks, 13:00-16:00 dip
    diurnal = [
        ("00:00", 1.24, 0.72, -3.5),
        ("03:00", 1.18, 0.65, -5.0),
        ("06:00", 1.32, 0.68, -5.5),
        ("09:00", 1.20, 0.85, -1.5),
        ("12:00", 0.82, 1.20, 3.5),
        ("15:00", 0.64, 1.45, 5.5),
        ("18:00", 1.08, 0.90, 1.0),
        ("21:00", 1.30, 0.74, -2.0),
    ]
    points: list[HourlyWindowPoint] = []
    safe_threshold = min(75.0, max(38.0, base_pm25 * 0.78))
    for label, pm_mult, wind_mult, temp_off in diurnal:
        pm_val = round(max(6.0, base_pm25 * pm_mult), 1)
        wind_val = round(max(1.5, base_wind * wind_mult), 1)
        temp_val = round(base_temp + temp_off, 1)
        points.append(
            HourlyWindowPoint(
                hour_label=label,
                pm2_5=pm_val,
                wind_kmh=wind_val,
                temp_c=temp_val,
                ventilation_safe=pm_val <= safe_threshold and wind_val >= 5.0,
            )
        )
    return points


def _fetch_hourly_context(lat: float, lon: float) -> tuple[Optional[float], Optional[float], list[HourlyWindowPoint]]:
    """Fetch 24h PM2.5 + weather wind/temperature from Open-Meteo in one lightweight pass."""
    aq_url = (
        f"https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}&hourly=pm2_5&forecast_days=1&timezone=auto"
    )
    wx_url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&current=temperature_2m,wind_speed_10m"
        f"&hourly=temperature_2m,wind_speed_10m&forecast_days=1&timezone=auto"
    )
    try:
        with httpx.Client(timeout=6.0) as client:
            aq_resp = client.get(aq_url)
            wx_resp = client.get(wx_url)
            aq_json = aq_resp.json()
            wx_json = wx_resp.json()

        wx_cur = wx_json.get("current", {})
        wind_now = wx_cur.get("wind_speed_10m")
        temp_now = wx_cur.get("temperature_2m")

        times = aq_json.get("hourly", {}).get("time", [])
        pms = aq_json.get("hourly", {}).get("pm2_5", [])
        winds = wx_json.get("hourly", {}).get("wind_speed_10m", [])
        temps = wx_json.get("hourly", {}).get("temperature_2m", [])

        if not times or not pms:
            return wind_now, temp_now, []

        valid_pms = [p for p in pms if p is not None]
        median_pm = sorted(valid_pms)[len(valid_pms) // 2] if valid_pms else 50.0
        safe_cutoff = min(80.0, max(35.0, median_pm * 0.85))

        points: list[HourlyWindowPoint] = []
        for idx in range(0, min(len(times), 24), 3):
            hhmm = times[idx].split("T")[-1][:5]
            pm_v = float(pms[idx] if pms[idx] is not None else median_pm)
            w_v = float(winds[idx] if idx < len(winds) and winds[idx] is not None else (wind_now or 6.0))
            t_v = float(temps[idx] if idx < len(temps) and temps[idx] is not None else (temp_now or 18.0))
            points.append(
                HourlyWindowPoint(
                    hour_label=hhmm,
                    pm2_5=round(pm_v, 1),
                    wind_kmh=round(w_v, 1),
                    temp_c=round(t_v, 1),
                    ventilation_safe=pm_v <= safe_cutoff and w_v >= 4.5,
                )
            )
        return wind_now, temp_now, points
    except Exception:
        return None, None, []


def get_presets() -> list[CityPreset]:
    return list(CITY_PRESETS.values())


def geocode_city(query: str) -> Optional[CityPreset]:
    """Resolve an arbitrary city name via Open-Meteo Geocoding API."""
    q = query.strip()
    if not q:
        return None
    low = q.lower().replace(" ", "_")
    if low in CITY_PRESETS:
        return CITY_PRESETS[low]
    for preset in CITY_PRESETS.values():
        if q.lower() in preset.name.lower():
            return preset

    url = f"https://geocoding-api.open-meteo.com/v1/search?name={httpx.QueryParams({'name': q})['name']}&count=1&language=en&format=json"
    try:
        with httpx.Client(timeout=6.0) as client:
            resp = client.get(url)
            results = resp.json().get("results", [])
        if not results:
            return None
        hit = results[0]
        city_id = f"custom_{hit['name'].lower().replace(' ', '_')}"
        return CityPreset(
            id=city_id,
            name=hit["name"],
            region=", ".join(filter(None, [hit.get("admin1"), hit.get("country")])),
            lat=float(hit["latitude"]),
            lon=float(hit["longitude"]),
            climate_note="Live geocoded urban airshed monitoring.",
            baseline_pm25=75.0,
            baseline_pm10=115.0,
            baseline_co=620.0,
            baseline_no2=35.0,
        )
    except Exception:
        return None


def get_city_air_quality(
    city_id: str = "bolpur",
    custom_city: Optional[CityPreset] = None,
    force_refresh: bool = False,
) -> AirQualityReport:
    """Fetch air quality using weather_api.get_live_air_quality with TTL cache & offline fallback."""
    preset = custom_city or CITY_PRESETS.get(city_id) or CITY_PRESETS["bolpur"]
    now = time.time()

    if not force_refresh and preset.id in _AQI_CACHE:
        cached_at, cached_report = _AQI_CACHE[preset.id]
        if now - cached_at < AQI_CACHE_TTL_SECONDS:
            return cached_report.model_copy(update={"data_source": "cached_open_meteo"})

    live_data = get_live_air_quality(lat=preset.lat, lon=preset.lon)
    if live_data is not None:
        pm25 = float(live_data.get("pm2_5", preset.baseline_pm25))
        pm10 = float(live_data.get("pm10", preset.baseline_pm10))
        co = float(live_data.get("co", preset.baseline_co))
        no2 = float(live_data.get("no2", preset.baseline_no2))
        wind_now, temp_now, hourly = _fetch_hourly_context(preset.lat, preset.lon)
        data_source = "live_open_meteo"
    else:
        pm25 = preset.baseline_pm25
        pm10 = preset.baseline_pm10
        co = preset.baseline_co
        no2 = preset.baseline_no2
        wind_now, temp_now, hourly = 4.8, 15.5, []
        data_source = "regional_fallback"

    if not hourly:
        hourly = _synthesize_hourly_profile(pm25, wind_now or 5.5, temp_now or 16.0)

    safe_windows = [pt.hour_label for pt in hourly if pt.ventilation_safe]
    if not safe_windows:
        # Pick the lowest PM2.5 hour as least-bad brief air exchange window
        best = min(hourly, key=lambda p: p.pm2_5)
        safe_windows = [f"{best.hour_label} (brief 10-min window)"]

    us_aqi, aqi_cat, aqi_color = pm25_to_us_aqi(pm25)
    inv_risk, inv_text = assess_inversion_risk(pm25, wind_now, temp_now)

    report = AirQualityReport(
        city_id=preset.id,
        city_name=preset.name,
        region=preset.region,
        lat=preset.lat,
        lon=preset.lon,
        pm2_5=round(pm25, 1),
        pm10=round(pm10, 1),
        co=round(co, 1),
        no2=round(no2, 1),
        us_aqi=us_aqi,
        aqi_category=aqi_cat,
        aqi_color=aqi_color,
        wind_kmh=round(wind_now, 1) if wind_now is not None else None,
        temp_c=round(temp_now, 1) if temp_now is not None else None,
        inversion_risk=inv_risk,
        inversion_explanation=inv_text,
        safe_ventilation_windows=safe_windows,
        hourly_profile=hourly,
        data_source=data_source,
        fetched_at_iso=datetime.now(timezone.utc).isoformat(),
    )

    if data_source == "live_open_meteo":
        _AQI_CACHE[preset.id] = (now, report)
    return report
