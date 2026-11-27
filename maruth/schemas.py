"""Pydantic schemas for Maruth telemetry, household profiling, impact modeling, and GenAI outputs."""

from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class CityPreset(BaseModel):
    id: str
    name: str
    region: str
    lat: float
    lon: float
    climate_note: str
    baseline_pm25: float
    baseline_pm10: float
    baseline_co: float
    baseline_no2: float


class HourlyWindowPoint(BaseModel):
    hour_label: str
    pm2_5: float
    wind_kmh: float
    temp_c: float
    ventilation_safe: bool


class AirQualityReport(BaseModel):
    city_id: str
    city_name: str
    region: str
    lat: float
    lon: float
    pm2_5: float
    pm10: float
    co: float
    no2: float
    us_aqi: int
    aqi_category: str
    aqi_color: str
    wind_kmh: Optional[float] = None
    temp_c: Optional[float] = None
    inversion_risk: Literal["LOW", "MODERATE", "HIGH", "SEVERE"]
    inversion_explanation: str
    safe_ventilation_windows: list[str]
    hourly_profile: list[HourlyWindowPoint]
    data_source: Literal["live_open_meteo", "cached_open_meteo", "regional_fallback"]
    fetched_at_iso: str


class DrosophilaTrace(BaseModel):
    time_s: list[float]
    input_signal: list[float]
    neural_signal: list[float]
    neuron_rates_hz: list[float]
    mean_firing_rate_hz: float


class DrosophilaBioSensorResult(BaseModel):
    live_pm2_5: float
    neural_response: float
    detected_pm2_5: float
    status: Literal["NORMAL", "HIGH POLLUTION"]
    alert_summary: str
    simulation_mode: Literal["live_nengo", "cached_nengo"]
    trace: Optional[DrosophilaTrace] = None


class HouseholdProfile(BaseModel):
    city_id: str = "bolpur"
    household_size: int = Field(default=4, ge=1, le=20)
    vulnerable_groups: list[str] = Field(default_factory=lambda: ["children", "elderly"])
    home_sealing: Literal["drafty", "average", "well_sealed"] = "average"
    room_volume_m3: float = Field(default=45.0, ge=12.0, le=300.0)
    cooking_fuel: Literal["lpg", "induction", "biomass_wood", "piped_gas"] = "lpg"
    heating_source: Literal["none", "electric_radiator", "wood_coal_stove", "heat_pump"] = "none"
    commute_mode: Literal["car_petrol_diesel", "two_wheeler", "public_transit", "walk_cycle", "ev_hybrid"] = "two_wheeler"
    daily_commute_km: float = Field(default=14.0, ge=0.0, le=150.0)
    budget_tier: Literal["zero_cost_diy", "low_cost", "appliance_upgrade"] = "low_cost"
    has_hepa_purifier: bool = False

    @field_validator("vulnerable_groups")
    @classmethod
    def sanitize_groups(cls, v: list[str]) -> list[str]:
        allowed = {"infants", "children", "elderly", "asthma_copd", "pregnant", "outdoor_worker"}
        return [item for item in v if item in allowed]


class InterventionCatalogItem(BaseModel):
    id: str
    pillar: Literal["routine", "iaq_hack", "sustainable_swap"]
    title: str
    subtitle: str
    budget_tier: Literal["zero_cost_diy", "low_cost", "appliance_upgrade"]
    cadr_m3h: float = 0.0
    infiltration_reduction_frac: float = 0.0
    indoor_source_reduction_ugm3: float = 0.0
    exposure_timing_reduction_frac: float = 0.0
    pm25_emission_saved_g_day: float = 0.0
    co2e_saved_kg_month: float = 0.0
    monthly_cost_delta_inr: float = 0.0  # negative = net savings, positive = net cost
    upfront_cost_inr: float = 0.0
    why_it_works: str
    how_to_steps: list[str]
    community_angle: Optional[str] = None
    applicable_tags: list[str] = Field(default_factory=list)


class RoutineSlot(BaseModel):
    time_window: str
    activity: str
    smog_risk: Literal["LOW", "MODERATE", "HIGH", "SEVERE"]
    recommendation: str
    impact_note: str


class ActionCard(BaseModel):
    intervention_id: str
    pillar: Literal["routine", "iaq_hack", "sustainable_swap"]
    title: str
    priority: Literal["ESSENTIAL", "HIGH_IMPACT", "BONUS"]
    tailored_guidance: str
    direct_impact_summary: str
    why_it_works: str
    steps: list[str]
    monthly_cost_note: str
    selected_by_default: bool = True


class ImpactSummary(BaseModel):
    outdoor_pm2_5: float
    baseline_indoor_pm2_5: float
    projected_indoor_pm2_5: float
    indoor_reduction_ugm3: float
    indoor_reduction_pct: float
    daily_inhaled_pm25_avoided_ug: float
    cigarette_equivalents_avoided_week: float
    community_pm25_emission_saved_g_day: float
    co2e_saved_kg_month: float
    net_monthly_cost_delta_inr: float
    upfront_cost_total_inr: float
    health_risk_tier_before: str
    health_risk_tier_after: str
    causal_breakdown: list[str]


class GenAITelemetry(BaseModel):
    provider_used: str
    model_tier: Literal["fast", "reasoning", "local_rag"]
    cache_hit: bool
    prompt_tokens_raw: int
    prompt_tokens_compressed: int
    compression_ratio_pct: float
    latency_ms: float
    tools_invoked: list[str]
    grounding_sources: list[str]


class ActionPlanResponse(BaseModel):
    headline: str
    drosophila_interpretation: str
    routine_schedule: list[RoutineSlot]
    action_cards: list[ActionCard]
    community_playbook: list[str]
    impact_summary: ImpactSummary
    telemetry: GenAITelemetry


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    city_id: str = "bolpur"
    profile: HouseholdProfile = Field(default_factory=HouseholdProfile)
    selected_interventions: list[str] = Field(default_factory=list)
    history: list[ChatTurn] = Field(default_factory=list)
    api_provider: Literal["auto", "gemini", "anthropic", "local"] = "auto"
    api_key: Optional[str] = None
    model_override: Optional[str] = None
