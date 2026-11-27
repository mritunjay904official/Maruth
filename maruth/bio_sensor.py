"""Bridge to drosophila_brain.py 10-neuron Nengo simulation with smart caching and trace output."""

from __future__ import annotations

import time
from typing import Optional

from drosophila_brain import run_drosophila_brain
from maruth.schemas import AirQualityReport, DrosophilaBioSensorResult, DrosophilaTrace

_BRAIN_CACHE: dict[tuple[str, float], tuple[float, DrosophilaBioSensorResult]] = {}
BRAIN_CACHE_TTL_SECONDS = 600


def evaluate_drosophila_sensor(
    air_report: AirQualityReport,
    override_pm25: Optional[float] = None,
    force_rerun: bool = False,
) -> DrosophilaBioSensorResult:
    """Run drosophila_brain.run_drosophila_brain() on live city PM2.5 or a custom stress-test level."""
    target_pm25 = round(float(override_pm25 if override_pm25 is not None else air_report.pm2_5), 1)
    cache_key = (air_report.city_id, target_pm25)
    now = time.time()

    if not force_rerun and cache_key in _BRAIN_CACHE:
        ts, cached = _BRAIN_CACHE[cache_key]
        if now - ts < BRAIN_CACHE_TTL_SECONDS:
            return cached.model_copy(update={"simulation_mode": "cached_nengo"})

    raw = run_drosophila_brain(
        lat=air_report.lat,
        lon=air_report.lon,
        air_data={
            "pm2_5": target_pm25,
            "pm10": air_report.pm10,
            "co": air_report.co,
            "no2": air_report.no2,
        },
        return_trace=True,
    )

    if "error" in raw:
        raise RuntimeError(raw["error"])

    status = raw["status"]
    detected = float(raw["detected_pm2_5"])
    neural_resp = float(raw["neural_response"])

    if status == "HIGH POLLUTION":
        alert_summary = (
            f"10-neuron Drosophila olfactory ensemble saturated at {neural_resp:.3f} "
            f"(decoded {detected:.1f} ug/m3 > 100 ug/m3 threshold): Immediate indoor filtration & mask trigger active."
        )
    else:
        alert_summary = (
            f"10-neuron Drosophila olfactory ensemble stabilized at {neural_resp:.3f} "
            f"(decoded {detected:.1f} ug/m3 <= 100 ug/m3): Baseline vigilance; keep clean-room & commute timing active."
        )

    trace_obj = DrosophilaTrace(**raw["trace"]) if "trace" in raw else None
    result = DrosophilaBioSensorResult(
        live_pm2_5=float(raw["live_pm2_5"]),
        neural_response=neural_resp,
        detected_pm2_5=detected,
        status=status,
        alert_summary=alert_summary,
        simulation_mode="live_nengo",
        trace=trace_obj,
    )
    _BRAIN_CACHE[cache_key] = (now, result)
    return result
