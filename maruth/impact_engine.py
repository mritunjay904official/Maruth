"""Deterministic IAQ mass-balance physics, emissions delta, and household cost impact engine."""

from __future__ import annotations

from maruth.schemas import (
    AirQualityReport,
    HouseholdProfile,
    ImpactSummary,
    InterventionCatalogItem,
)

INTERVENTION_CATALOG: dict[str, InterventionCatalogItem] = {
    "ventilation_window_sync": InterventionCatalogItem(
        id="ventilation_window_sync",
        pillar="routine",
        title="Sync Window Opening to Afternoon Thermal Mixing",
        subtitle="Flush CO2 & indoor odors only during lowest PM2.5 window; keep shut during morning/evening inversion.",
        budget_tier="zero_cost_diy",
        infiltration_reduction_frac=0.14,
        exposure_timing_reduction_frac=0.10,
        monthly_cost_delta_inr=0.0,
        upfront_cost_inr=0.0,
        why_it_works="Winter inversions trap smog near ground at night and dawn. Shifting natural airing to mid-afternoon (13:00-16:00) cuts outdoor PM2.5 ingress while clearing stale CO2.",
        how_to_steps=[
            "Keep exterior windows latched from 19:00 through 11:00 during inversion episodes.",
            "Open opposite-facing windows for 15-20 minutes during the safest afternoon window shown on the radar.",
            "Close immediately if local burning or heavy traffic passes outside.",
        ],
        community_angle="Share daily safe-airing window alerts in your apartment or neighborhood WhatsApp group.",
        applicable_tags=["all"],
    ),
    "smog_shifted_commute": InterventionCatalogItem(
        id="smog_shifted_commute",
        pillar="routine",
        title="Peak-Smog Commute Shift + N95 / Trip Bundling",
        subtitle="Avoid 07:00-09:30 street-canyon peaks, bundle errands, and wear snug N95/FFP2 when AQI > 150.",
        budget_tier="low_cost",
        exposure_timing_reduction_frac=0.22,
        pm25_emission_saved_g_day=1.8,
        co2e_saved_kg_month=18.0,
        monthly_cost_delta_inr=-450.0,
        upfront_cost_inr=250.0,
        why_it_works="Roadside PM2.5 and NO2 spike 2-3x during morning rush under cold inversions. Trip bundling reduces cold-start engine emissions and N95 respirators block >95% of fine particles.",
        how_to_steps=[
            "Batch grocery, pharmacy, and school pickups into one afternoon trip instead of 2-3 cold starts.",
            "Use a well-fitted N95/KN95 (pinch nose wire) whenever outdoor PM2.5 exceeds 55 ug/m3.",
            "Switch outdoor jogging or brisk walks indoors on HIGH POLLUTION days.",
        ],
        community_angle="Organize a 3-family school carpool or walking-bus along side streets away from arterial roads.",
        applicable_tags=["two_wheeler", "car_petrol_diesel", "walk_cycle", "children"],
    ),
    "door_window_weatherstrip": InterventionCatalogItem(
        id="door_window_weatherstrip",
        pillar="iaq_hack",
        title="Door & Window Gap Sealing (Foam Tape + Wet Towel Draft Stop)",
        subtitle="Block unfiltered smog infiltration around sliding frames and under doors.",
        budget_tier="zero_cost_diy",
        infiltration_reduction_frac=0.34,
        monthly_cost_delta_inr=-120.0,
        upfront_cost_inr=180.0,
        why_it_works="In typical urban homes, air leaks around window channels and door gaps drive 50-70% of indoor PM2.5 infiltration. Cutting air-exchange leakage immediately slows outdoor smoke entry and retains indoor warmth.",
        how_to_steps=[
            "Place a rolled damp cloth or draft snake along the bottom gap of exterior doors.",
            "Apply adhesive EPDM foam weatherstripping along sliding window tracks (or masking tape for temporary winter sealing).",
            "Designate one bedroom as the 'Clean Air Sanctuary' for children and elders.",
        ],
        applicable_tags=["drafty", "average", "elderly", "children", "asthma_copd"],
    ),
    "wet_mop_source_control": InterventionCatalogItem(
        id="wet_mop_source_control",
        pillar="iaq_hack",
        title="Wet Mopping & Indoor Smoke Elimination",
        subtitle="Replace dry brooming with damp microfiber mopping; pause incense, coils, and unvented candles.",
        budget_tier="zero_cost_diy",
        indoor_source_reduction_ugm3=26.0,
        pm25_emission_saved_g_day=2.4,
        co2e_saved_kg_month=4.0,
        monthly_cost_delta_inr=-150.0,
        upfront_cost_inr=0.0,
        why_it_works="Dry sweeping re-suspends settled toxic dust back into breathing height (0.5-1.5m). One incense stick or mosquito coil indoors can spike bedroom PM2.5 above 250 ug/m3.",
        how_to_steps=[
            "Switch from dry broom sweeping to damp mopping every morning.",
            "Use electric liquid vaporizers or bed nets instead of burning mosquito coils; keep pooja lamps/incense near an open balcony or exhaust.",
            "Cover pans while frying/tadka and run kitchen exhaust fan during cooking.",
        ],
        applicable_tags=["all", "asthma_copd", "infants", "children"],
    ),
    "diy_corsi_rosenthal_cr_box": InterventionCatalogItem(
        id="diy_corsi_rosenthal_cr_box",
        pillar="iaq_hack",
        title="DIY Box-Fan HEPA / MERV-13 Air Scrubber (CR Box)",
        subtitle="High-CADR (~320 m3/h) DIY purifier using a standard table/box fan + MERV-13/HEPA filter panel.",
        budget_tier="low_cost",
        cadr_m3h=320.0,
        monthly_cost_delta_inr=220.0,
        upfront_cost_inr=1650.0,
        why_it_works="Clean Air Delivery Rate (CADR) determines how fast particles are scrubbed from a room. A DIY fan+filter box delivers purifier-grade 6+ air changes per hour in a 45 m3 bedroom at ~1/5th commercial purifier cost.",
        how_to_steps=[
            "Tape a MERV-13 or replacement HEPA filter (or 2-4 filter cube) securely onto the intake side of a 16-inch box/pedestal fan.",
            "Seal every cardboard/frame seam with duct tape so air cannot bypass the filter media.",
            "Run on medium-high 30 minutes before bedtime and keep on low overnight in the sealed bedroom.",
        ],
        community_angle="Host a weekend RWA/school workshop to bulk-buy MERV-13 filters and build 10 CR Boxes for elders and classrooms.",
        applicable_tags=["low_cost", "appliance_upgrade", "asthma_copd", "children", "elderly"],
    ),
    "hepa_purifier_operation": InterventionCatalogItem(
        id="hepa_purifier_operation",
        pillar="iaq_hack",
        title="True HEPA Purifier Sizing & Continuous Auto-Mode",
        subtitle="Run HEPA purifier sized at >= 5 ACH in closed sleeping zones (avoid ionizers/ozone modes).",
        budget_tier="appliance_upgrade",
        cadr_m3h=400.0,
        monthly_cost_delta_inr=380.0,
        upfront_cost_inr=7500.0,
        why_it_works="True H13 HEPA captures 99.95% of 0.3 um ultrafine soot particles. Running it continuously in a sealed room drops indoor PM2.5 by 70-85% within 45 minutes.",
        how_to_steps=[
            "Place purifier 30 cm away from walls; never run ozone/ionizer buttons.",
            "Keep bedroom door closed so CADR isn't diluted across the whole house.",
            "Vacuum the outer pre-filter mesh weekly to sustain airflow and extend HEPA life.",
        ],
        applicable_tags=["appliance_upgrade", "has_hepa", "asthma_copd", "infants"],
    ),
    "clean_cooking_induction_swap": InterventionCatalogItem(
        id="clean_cooking_induction_swap",
        pillar="sustainable_swap",
        title="Electric Kettle / Induction Swap + Exhaust Cross-Draft",
        subtitle="Shift boiling, tea, and light cooking from biomass/gas burners to induction/electric kettle.",
        budget_tier="low_cost",
        indoor_source_reduction_ugm3=32.0,
        pm25_emission_saved_g_day=8.5,
        co2e_saved_kg_month=34.0,
        monthly_cost_delta_inr=-320.0,
        upfront_cost_inr=1900.0,
        why_it_works="Biomass and gas combustion release indoor NO2, CO, and ultrafine soot directly into the home. Shifting 50%+ of daily boiling/simmering to electric induction slashes kitchen PM2.5 and outdoor neighborhood smoke.",
        how_to_steps=[
            "Use an electric kettle for morning tea/water and induction cooktop for dal, rice, and reheating.",
            "If using biomass/wood outdoors, switch to processed biomass pellets or LPG subsidy refills.",
            "Run kitchen exhaust or crack a window while sauteing to purge cooking aerosols.",
        ],
        community_angle="Support community clean-kitchen transitions or shared solar-induction hubs for winter evenings.",
        applicable_tags=["biomass_wood", "lpg", "piped_gas", "all"],
    ),
    "clean_heating_no_burn": InterventionCatalogItem(
        id="clean_heating_no_burn",
        pillar="sustainable_swap",
        title="Zero-Burn Warmth & Leaf/Trash Composting Pact",
        subtitle="Replace coal/wood space heating and dry-leaf bonfires with layered woolens, hot-water bags, or oil-filled radiators.",
        budget_tier="zero_cost_diy",
        indoor_source_reduction_ugm3=28.0,
        pm25_emission_saved_g_day=18.0,
        co2e_saved_kg_month=42.0,
        monthly_cost_delta_inr=-260.0,
        upfront_cost_inr=0.0,
        why_it_works="Open wood/coal braziers and backyard leaf burning emit massive primary PM2.5 plumes directly under night inversions—affecting up to 50 nearby homes simultaneously.",
        how_to_steps=[
            "Stop burning garden leaves, cardboard, or winter trash; bag dry leaves for municipal compost pits.",
            "Layer thermal curtains, rugs, and hot-water bottles instead of open coal/wood sigris.",
            "If electric heating is needed, use a thermostatic oil-filled radiator only in occupied sealed rooms.",
        ],
        community_angle="Start a neighborhood 'Zero Bonfire Night Watch' with your security guards and RWA—provide guards with insulated jackets & thermos tea instead of wood fires.",
        applicable_tags=["wood_coal_stove", "all", "bolpur", "kolkata", "delhi_ncr"],
    ),
    "transit_carpool_ev_shift": InterventionCatalogItem(
        id="transit_carpool_ev_shift",
        pillar="sustainable_swap",
        title="Transit / Carpool / E-Micro-Mobility Shift (3+ Days/Week)",
        subtitle="Replace solo fossil-fuel trips with metro/bus, e-rickshaw, bicycle (off-peak), or 3-person carpool.",
        budget_tier="zero_cost_diy",
        pm25_emission_saved_g_day=4.2,
        co2e_saved_kg_month=52.0,
        monthly_cost_delta_inr=-1400.0,
        upfront_cost_inr=0.0,
        why_it_works="Tailpipe exhaust and brake/tire wear emit ultrafine particles at breathing height. Replacing even 3 solo commute days/week with shared transit or EVs removes ~52 kg CO2e/month and cuts roadside NO2.",
        how_to_steps=[
            "Identify 2-3 coworkers or school parents along your route for alternating winter carpools.",
            "Use metro/electric bus/e-rickshaw for congested market corridors.",
            "Check tire pressure monthly—underinflated tires increase fuel burn and tire-wear PM.",
        ],
        community_angle="Ask schools/offices to enforce a strict 'Engine Off' no-idling drop-off zone within 100m of gates.",
        applicable_tags=["car_petrol_diesel", "two_wheeler"],
    ),
}


def get_default_interventions(profile: HouseholdProfile) -> list[str]:
    """Select sensible default interventions matching the user's household profile & budget."""
    selected = ["ventilation_window_sync", "door_window_weatherstrip", "wet_mop_source_control"]

    if profile.budget_tier in ("low_cost", "appliance_upgrade") or profile.daily_commute_km > 3:
        selected.append("smog_shifted_commute")

    if profile.has_hepa_purifier or profile.budget_tier == "appliance_upgrade":
        selected.append("hepa_purifier_operation")
    elif profile.budget_tier == "low_cost":
        selected.append("diy_corsi_rosenthal_cr_box")

    if profile.cooking_fuel in ("biomass_wood", "lpg", "piped_gas"):
        selected.append("clean_cooking_induction_swap")

    if profile.heating_source == "wood_coal_stove" or profile.city_id in ("bolpur", "kolkata", "delhi_ncr"):
        selected.append("clean_heating_no_burn")

    if profile.commute_mode in ("car_petrol_diesel", "two_wheeler"):
        selected.append("transit_carpool_ev_shift")

    # Preserve catalog order and deduplicate
    return [k for k in INTERVENTION_CATALOG if k in set(selected)]


def _risk_tier_label(pm25: float) -> str:
    if pm25 <= 15.0:
        return "WHO Safe (<15 ug/m3)"
    if pm25 <= 35.0:
        return "Moderate (15-35 ug/m3)"
    if pm25 <= 75.0:
        return "Elevated (35-75 ug/m3)"
    if pm25 <= 150.0:
        return "High Exposure (75-150 ug/m3)"
    return "Severe Smog (>150 ug/m3)"


def calculate_impact_delta(
    air_report: AirQualityReport,
    profile: HouseholdProfile,
    selected_ids: list[str],
) -> ImpactSummary:
    """
    Deterministic single-zone indoor PM2.5 mass-balance model:
      C_in = (P * AER * C_out + S_in / V) / (AER + k_dep + CADR / V)
    Combined with commute/cooking/heating emission factors & household economics.
    """
    c_out = max(1.0, air_report.pm2_5)
    v_room = profile.room_volume_m3

    # Base building envelope parameters
    aer_map = {"drafty": 1.35, "average": 0.75, "well_sealed": 0.35}
    pen_map = {"drafty": 0.85, "average": 0.72, "well_sealed": 0.58}
    base_aer = aer_map[profile.home_sealing]
    penetration = pen_map[profile.home_sealing]
    k_dep = 0.35  # natural gravitational settling rate (1/hr)

    # Indoor baseline sources (ug/m3 equivalent generation contribution S/V * tau)
    cooking_source = {"biomass_wood": 58.0, "lpg": 22.0, "piped_gas": 16.0, "induction": 6.0}[profile.cooking_fuel]
    heating_source = {"none": 0.0, "electric_radiator": 2.0, "heat_pump": 1.0, "wood_coal_stove": 68.0}[
        profile.heating_source
    ]
    baseline_cadr = 240.0 if profile.has_hepa_purifier else 0.0

    # Baseline indoor PM2.5
    base_source_rate = (cooking_source + heating_source) * (base_aer + k_dep)
    baseline_indoor = (penetration * base_aer * c_out + base_source_rate) / (
        base_aer + k_dep + (baseline_cadr / v_room)
    )
    baseline_indoor = round(max(4.0, baseline_indoor), 1)

    # Apply chosen interventions
    active_items = [INTERVENTION_CATALOG[i] for i in selected_ids if i in INTERVENTION_CATALOG]

    infil_cut = 1.0
    for item in active_items:
        infil_cut *= 1.0 - item.infiltration_reduction_frac
    eff_aer = max(0.20, base_aer * infil_cut)

    extra_cadr = sum(item.cadr_m3h for item in active_items)
    # Avoid double-counting baseline HEPA if hepa_purifier_operation is also toggled
    total_cadr = max(baseline_cadr, extra_cadr) if "hepa_purifier_operation" in selected_ids else baseline_cadr + extra_cadr

    source_reduction_ug = sum(item.indoor_source_reduction_ugm3 for item in active_items)
    eff_source_conc = max(3.0, (cooking_source + heating_source) - source_reduction_ug)
    eff_source_rate = eff_source_conc * (eff_aer + k_dep)

    projected_indoor = (penetration * eff_aer * c_out + eff_source_rate) / (
        eff_aer + k_dep + (total_cadr / v_room)
    )

    # Account for outdoor routine timing shift (weighted ~25% of daily exposure)
    timing_cut = sum(item.exposure_timing_reduction_frac for item in active_items)
    timing_cut = min(0.35, timing_cut)
    projected_indoor = projected_indoor * (1.0 - 0.18 * timing_cut)
    projected_indoor = round(max(3.5, min(baseline_indoor, projected_indoor)), 1)

    reduction_ug = round(max(0.0, baseline_indoor - projected_indoor), 1)
    reduction_pct = round((reduction_ug / baseline_indoor) * 100.0, 1) if baseline_indoor > 0 else 0.0

    # Daily inhaled PM2.5 avoided across household (~12 m3/day resting/indoor breathing per person)
    daily_inhaled_avoided = round(reduction_ug * 12.0 * profile.household_size, 0)
    # Berkeley Earth rule of thumb: ~22 ug/m3 PM2.5 over 24h ~= 1 cigarette/day per person
    cigs_avoided_week = round((reduction_ug / 22.0) * 7.0, 1)

    # Community emission reductions scaled by commute km & cooking/heating habits
    commute_scale = max(0.4, min(2.0, profile.daily_commute_km / 14.0))
    pm_saved_day = 0.0
    co2_saved_month = 0.0
    net_monthly_inr = 0.0
    upfront_total_inr = 0.0
    causal: list[str] = []

    for item in active_items:
        scale = commute_scale if item.pillar == "sustainable_swap" and "transit" in item.id else 1.0
        pm_saved_day += item.pm25_emission_saved_g_day * scale
        co2_saved_month += item.co2e_saved_kg_month * scale
        net_monthly_inr += item.monthly_cost_delta_inr
        upfront_total_inr += item.upfront_cost_inr

    if total_cadr > 0:
        ach = round(total_cadr / v_room, 1)
        causal.append(
            f"Active filtration ({int(total_cadr)} m3/h CADR -> {ach} air changes/hr in a {int(v_room)} m3 room) continuously strips infiltrating ultrafine soot."
        )
    if infil_cut < 0.99:
        pct_seal = round((1.0 - infil_cut) * 100)
        causal.append(
            f"Envelope sealing & window-timing cut outdoor smog infiltration rate by ~{pct_seal}% (from {base_aer:.2f} to {eff_aer:.2f} ACH)."
        )
    if source_reduction_ug > 0:
        causal.append(
            f"Eliminating indoor combustion/re-suspension removes ~{int(min(source_reduction_ug, cooking_source + heating_source))} ug/m3 of self-generated indoor PM2.5 & NO2."
        )
    if pm_saved_day > 0:
        causal.append(
            f"Clean commute & zero-burn swaps prevent {pm_saved_day:.1f} g/day of direct primary PM2.5 from entering your street's breathing zone."
        )

    return ImpactSummary(
        outdoor_pm2_5=round(c_out, 1),
        baseline_indoor_pm2_5=baseline_indoor,
        projected_indoor_pm2_5=projected_indoor,
        indoor_reduction_ugm3=reduction_ug,
        indoor_reduction_pct=reduction_pct,
        daily_inhaled_pm25_avoided_ug=daily_inhaled_avoided,
        cigarette_equivalents_avoided_week=cigs_avoided_week,
        community_pm25_emission_saved_g_day=round(pm_saved_day, 1),
        co2e_saved_kg_month=round(co2_saved_month, 1),
        net_monthly_cost_delta_inr=round(net_monthly_inr, 0),
        upfront_cost_total_inr=round(upfront_total_inr, 0),
        health_risk_tier_before=_risk_tier_label(baseline_indoor),
        health_risk_tier_after=_risk_tier_label(projected_indoor),
        causal_breakdown=causal,
    )
