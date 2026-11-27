"""Multi-provider GenAI orchestrator with tool calling, model-tier routing, plan caching, and SSE streaming."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from typing import Any, AsyncIterator, Optional
import httpx

from maruth.air_quality import get_city_air_quality
from maruth.bio_sensor import evaluate_drosophila_sensor
from maruth.impact_engine import (
    INTERVENTION_CATALOG,
    calculate_impact_delta,
    get_default_interventions,
)
from maruth.knowledge_base import search_smog_playbook
from maruth.prompts import (
    GEMINI_TOOL_DECLARATIONS,
    MARUTH_SYSTEM_PROMPT,
    compress_chat_history,
    compress_context,
    estimate_tokens,
)
from maruth.schemas import (
    ActionCard,
    ActionPlanResponse,
    AirQualityReport,
    ChatRequest,
    DrosophilaBioSensorResult,
    GenAITelemetry,
    HouseholdProfile,
    ImpactSummary,
    RoutineSlot,
)

# Plan cache keyed by (city_id, pm25_bucket, drosophila_status, profile_hash, selected_hash, provider_mode)
_PLAN_CACHE: dict[str, tuple[float, ActionPlanResponse]] = {}
PLAN_CACHE_TTL_SECONDS = 600

# Runtime optimization telemetry counters
_TELEMETRY_STATS = {
    "total_requests": 0,
    "cache_hits": 0,
    "tokens_saved_by_compression": 0,
    "tokens_saved_by_cache": 0,
    "tool_calls_executed": 0,
}


def get_optimization_stats() -> dict[str, Any]:
    return dict(_TELEMETRY_STATS)


def _profile_fingerprint(
    air: AirQualityReport,
    brain: DrosophilaBioSensorResult,
    profile: HouseholdProfile,
    selected_ids: list[str],
    provider_mode: str,
) -> str:
    pm_bucket = int(air.pm2_5 // 25) * 25
    payload = json.dumps(
        {
            "city": air.city_id,
            "pm_bucket": pm_bucket,
            "bio_status": brain.status,
            "profile": profile.model_dump(),
            "selected": sorted(selected_ids),
            "provider": provider_mode,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _resolve_provider_and_key(
    requested_provider: str,
    user_api_key: Optional[str],
) -> tuple[str, Optional[str]]:
    """Select active GenAI provider from user key or environment variables."""
    key = (user_api_key or "").strip()
    if requested_provider == "local":
        return "local_rag", None

    if requested_provider == "gemini" or (requested_provider == "auto" and (key.startswith("AIza") or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))):
        resolved_key = key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if resolved_key:
            return "gemini", resolved_key

    if requested_provider == "anthropic" or (requested_provider == "auto" and (key.startswith("sk-ant-") or os.environ.get("ANTHROPIC_API_KEY"))):
        resolved_key = key or os.environ.get("ANTHROPIC_API_KEY")
        if resolved_key:
            return "anthropic", resolved_key

    if key:
        # User provided a key explicitly with matching provider or fallback to Gemini
        return ("anthropic" if requested_provider == "anthropic" else "gemini"), key

    return "local_rag", None


def _execute_tool_call(
    tool_name: str,
    args: dict[str, Any],
    default_city_id: str,
    profile: HouseholdProfile,
    selected_ids: list[str],
) -> dict[str, Any]:
    """Execute grounded Maruth tools invoked by the LLM."""
    _TELEMETRY_STATS["tool_calls_executed"] += 1
    if tool_name == "get_live_air_quality_tool":
        report = get_city_air_quality(args.get("city_id") or default_city_id)
        return report.model_dump(exclude={"hourly_profile"})
    if tool_name == "run_drosophila_biosensor_tool":
        report = get_city_air_quality(args.get("city_id") or default_city_id)
        bio = evaluate_drosophila_sensor(report)
        return bio.model_dump(exclude={"trace"})
    if tool_name == "calculate_impact_delta_tool":
        report = get_city_air_quality(default_city_id)
        chosen = args.get("selected_interventions") or selected_ids
        impact = calculate_impact_delta(report, profile, chosen)
        return impact.model_dump()
    if tool_name == "search_smog_playbook_tool":
        docs = search_smog_playbook(args.get("query", "winter smog"), top_k=3)
        return {"matches": [{"title": d.title, "content": d.content, "citation": d.citation} for d in docs]}
    return {"error": f"Unknown tool: {tool_name}"}


def _build_local_routine_schedule(
    air: AirQualityReport,
    brain: DrosophilaBioSensorResult,
    profile: HouseholdProfile,
) -> list[RoutineSlot]:
    """Synthesize smog-synchronized daily routine slots from live hourly profile."""
    safe_set = set(air.safe_ventilation_windows)
    vuln_note = (
        f"Protect {', '.join(profile.vulnerable_groups)} indoors."
        if profile.vulnerable_groups
        else "Keep bedroom clean-air zone sealed."
    )
    mask_note = "N95/FFP2 mandatory outdoors" if air.pm2_5 > 55 else "Light mask near busy roads"

    morning_risk = "SEVERE" if air.pm2_5 >= 150 else ("HIGH" if air.pm2_5 >= 80 else "MODERATE")
    afternoon_risk = "MODERATE" if air.pm2_5 >= 120 else "LOW"
    evening_risk = "SEVERE" if air.inversion_risk in ("HIGH", "SEVERE") else "HIGH"

    afternoon_win = air.safe_ventilation_windows[0] if air.safe_ventilation_windows else "14:00-15:30"
    is_afternoon_clean = any("12:" in w or "14:" in w or "15:" in w for w in safe_set)

    return [
        RoutineSlot(
            time_window="06:00 - 09:30",
            activity="Morning Commute & Home Prep",
            smog_risk=morning_risk,
            recommendation=f"Delay non-essential outdoor exercise; wear {mask_note}; damp-mop floors instead of dry sweeping. {vuln_note}",
            impact_note="Avoids peak morning inversion plume (~1.3x daily mean PM2.5) and prevents indoor dust resuspension.",
        ),
        RoutineSlot(
            time_window="12:30 - 16:00",
            activity="Thermal-Mixing Window & Errands",
            smog_risk=afternoon_risk,
            recommendation=(
                f"Best window ({afternoon_win}) for 15-min cross-ventilation to purge CO2, batch errands/school pickups, and solar-dry laundry."
                if is_afternoon_clean
                else f"Brief 10-min window around {afternoon_win} to purge stale indoor CO2; bundle errands into one trip."
            ),
            impact_note="Afternoon warming lifts the boundary layer, reducing ground PM2.5 by ~25-40% vs dawn/night.",
        ),
        RoutineSlot(
            time_window="16:30 - 20:00",
            activity="Cooking & Evening Transition",
            smog_risk="HIGH" if air.pm2_5 >= 90 else "MODERATE",
            recommendation=(
                "Latch exterior windows before sunset; boil/simmer on induction or electric kettle with kitchen exhaust on."
                if profile.cooking_fuel != "induction"
                else "Latch exterior windows before sunset; run kitchen exhaust while cooking."
            ),
            impact_note="Blocks onset of evening inversion and slashes indoor NO2 + cooking aerosols by up to 60%.",
        ),
        RoutineSlot(
            time_window="20:00 - 06:00",
            activity="Night Clean-Air Sanctuary",
            smog_risk=evening_risk,
            recommendation=(
                "Run DIY CR-Box or HEPA purifier in sealed bedroom; skip incense/mosquito coils; zero outdoor wood/leaf fires."
                if (profile.has_hepa_purifier or profile.budget_tier != "zero_cost_diy")
                else "Keep bedroom sealed with door draft-stop, damp cloth on gaps, and no coils/incense overnight."
            ),
            impact_note=f"Drosophila bio-sensor status ({brain.status}) triggers continuous overnight clean-zone protection.",
        ),
    ]


def _build_action_cards(
    air: AirQualityReport,
    profile: HouseholdProfile,
    selected_ids: list[str],
) -> list[ActionCard]:
    """Generate personalized ActionCards across all 3 pillars."""
    cards: list[ActionCard] = []
    selected_set = set(selected_ids)

    for item_id, item in INTERVENTION_CATALOG.items():
        # Filter out pure duplicate HEPA card if user chose zero-cost and has no HEPA
        if item_id == "hepa_purifier_operation" and profile.budget_tier == "zero_cost_diy" and not profile.has_hepa_purifier:
            continue

        # Compute single-intervention impact note cleanly
        single = calculate_impact_delta(air, profile, [item_id])
        cost_str = (
            f"Saves ~Rs {abs(int(item.monthly_cost_delta_inr))}/mo"
            if item.monthly_cost_delta_inr < 0
            else (f"~Rs {int(item.monthly_cost_delta_inr)}/mo operating cost" if item.monthly_cost_delta_inr > 0 else "Rs 0 monthly cost")
        )
        if item.upfront_cost_inr > 0:
            cost_str += f" (Upfront ~Rs {int(item.upfront_cost_inr)})"

        priority = "ESSENTIAL"
        if item.cadr_m3h >= 300 or item.infiltration_reduction_frac >= 0.30 or item.indoor_source_reduction_ugm3 >= 25:
            priority = "ESSENTIAL"
        elif item.co2e_saved_kg_month >= 30 or item.exposure_timing_reduction_frac >= 0.20:
            priority = "HIGH_IMPACT"
        else:
            priority = "BONUS"

        tailored = item.subtitle
        if profile.vulnerable_groups and item.pillar == "iaq_hack":
            tailored = f"Priority for {', '.join(profile.vulnerable_groups)}: {item.subtitle}"
        elif item_id == "clean_heating_no_burn" and air.city_id in ("bolpur", "kolkata", "delhi_ncr"):
            tailored = f"High-leverage for {air.city_name} winter nights: {item.subtitle}"

        direct_summary = (
            f"Lowers room PM2.5 by {single.indoor_reduction_ugm3} ug/m3 (-{single.indoor_reduction_pct}%)"
            if single.indoor_reduction_ugm3 >= 1.5
            else f"Avoids {single.community_pm25_emission_saved_g_day} g/day PM2.5 & {single.co2e_saved_kg_month} kg/mo CO2e"
        )
        if single.community_pm25_emission_saved_g_day > 0 and single.indoor_reduction_ugm3 >= 1.5:
            direct_summary += f" + saves {single.community_pm25_emission_saved_g_day} g/day local PM2.5"

        cards.append(
            ActionCard(
                intervention_id=item.id,
                pillar=item.pillar,
                title=item.title,
                priority=priority,
                tailored_guidance=tailored,
                direct_impact_summary=direct_summary,
                why_it_works=item.why_it_works,
                steps=item.how_to_steps,
                monthly_cost_note=cost_str,
                selected_by_default=(item.id in selected_set),
            )
        )
    return cards


async def _call_gemini_json_plan(
    api_key: str,
    model_name: str,
    compact_context: str,
) -> Optional[dict[str, Any]]:
    """Call Gemini REST API with strict JSON response schema for headline & community playbook."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    prompt = (
        f"{MARUTH_SYSTEM_PROMPT}\n\n"
        f"CONTEXT:\n{compact_context}\n\n"
        "Return a strict JSON object with keys: "
        "'headline' (1 punchy sentence tailored to this city & household), "
        "'drosophila_interpretation' (1-2 sentences explaining the Nengo bio-sensor reading & threshold), "
        "'community_playbook' (array of 3 specific neighborhood/RWA/school actions for this city)."
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 500,
            "responseMimeType": "application/json",
        },
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except Exception:
        return None


async def _call_anthropic_json_plan(
    api_key: str,
    compact_context: str,
) -> Optional[dict[str, Any]]:
    """Call Anthropic Claude SDK in a worker thread with compact prompt."""
    try:
        import anthropic

        def _sync_call() -> str:
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-3-5-haiku-latest",
                max_tokens=500,
                temperature=0.25,
                system=MARUTH_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"CONTEXT:\n{compact_context}\n\n"
                            "Respond ONLY with valid JSON containing keys: "
                            "'headline', 'drosophila_interpretation', 'community_playbook' (list of 3 strings)."
                        ),
                    }
                ],
            )
            return msg.content[0].text

        raw_text = await asyncio.to_thread(_sync_call)
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(raw_text[start : end + 1])
        return None
    except Exception:
        return None


async def generate_action_plan(
    air: AirQualityReport,
    brain: DrosophilaBioSensorResult,
    profile: HouseholdProfile,
    selected_interventions: Optional[list[str]] = None,
    api_provider: str = "auto",
    api_key: Optional[str] = None,
) -> ActionPlanResponse:
    """Generate a complete, impact-verified, cached ActionPlanResponse."""
    t0 = time.perf_counter()
    _TELEMETRY_STATS["total_requests"] += 1

    chosen = selected_interventions if selected_interventions is not None else get_default_interventions(profile)
    provider_mode, resolved_key = _resolve_provider_and_key(api_provider, api_key)

    fp = _profile_fingerprint(air, brain, profile, chosen, provider_mode)
    now = time.time()
    if fp in _PLAN_CACHE:
        ts, cached_plan = _PLAN_CACHE[fp]
        if now - ts < PLAN_CACHE_TTL_SECONDS:
            _TELEMETRY_STATS["cache_hits"] += 1
            _TELEMETRY_STATS["tokens_saved_by_cache"] += cached_plan.telemetry.prompt_tokens_compressed
            # Always recompute deterministic impact so toggles feel live even on plan cache hit
            fresh_impact = calculate_impact_delta(air, profile, chosen)
            updated_tele = cached_plan.telemetry.model_copy(
                update={
                    "cache_hit": True,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
            return cached_plan.model_copy(update={"impact_summary": fresh_impact, "telemetry": updated_tele})

    impact = calculate_impact_delta(air, profile, chosen)
    rag_query = (
        f"{air.city_name} winter smog {air.inversion_risk} {' '.join(profile.vulnerable_groups)} "
        f"{profile.cooking_fuel} {profile.budget_tier} {brain.status}"
    )
    rag_docs = search_smog_playbook(rag_query, top_k=3)
    rag_snippets = [f"[{d.title}] {d.content}" for d in rag_docs]

    compact_ctx, raw_tok, comp_tok, ratio_pct = compress_context(air, brain, profile, impact, rag_snippets)
    _TELEMETRY_STATS["tokens_saved_by_compression"] += max(0, raw_tok - comp_tok)

    # Model-tier routing: use reasoning tier when pollution is HIGH/SEVERE or vulnerable groups present
    use_reasoning = brain.status == "HIGH POLLUTION" or bool(profile.vulnerable_groups)
    model_tier = "reasoning" if (provider_mode != "local_rag" and use_reasoning) else (
        "fast" if provider_mode != "local_rag" else "local_rag"
    )

    llm_override: Optional[dict[str, Any]] = None
    active_provider_label = "Maruth Local RAG + Physics Engine"
    if provider_mode == "gemini" and resolved_key:
        model_name = "gemini-2.5-pro" if use_reasoning else "gemini-2.5-flash"
        llm_override = await _call_gemini_json_plan(resolved_key, model_name, compact_ctx)
        if llm_override:
            active_provider_label = f"Google Gemini ({model_name})"
    elif provider_mode == "anthropic" and resolved_key:
        llm_override = await _call_anthropic_json_plan(resolved_key, compact_ctx)
        if llm_override:
            active_provider_label = "Anthropic Claude (Haiku)"

    if not llm_override:
        model_tier = "local_rag"

    headline = (
        llm_override.get("headline")
        if llm_override and isinstance(llm_override.get("headline"), str)
        else (
            f"{air.city_name} is at US AQI {air.us_aqi} ({air.aqi_category}): activating your selected habits cuts indoor PM2.5 "
            f"from {impact.baseline_indoor_pm2_5} to {impact.projected_indoor_pm2_5} ug/m3 (-{impact.indoor_reduction_pct}%)."
        )
    )
    bio_interp = (
        llm_override.get("drosophila_interpretation")
        if llm_override and isinstance(llm_override.get("drosophila_interpretation"), str)
        else brain.alert_summary
    )
    community_playbook = (
        [str(x) for x in llm_override.get("community_playbook", [])[:4]]
        if llm_override and isinstance(llm_override.get("community_playbook"), list) and llm_override.get("community_playbook")
        else [
            f"{air.city_name} Night Watch: replace open dry-leaf/wood guard fires with insulated jackets & thermos tea during {air.inversion_risk} inversion nights.",
            "Apartment/RWA Bulk Filter Drive: pool 10 households to build DIY MERV-13 CR-Boxes (~Rs 1,650/room) for elders and infants.",
            "School & Transit No-Idling Pact: form 3-family carpools and enforce engine-off zones 100m around school gates.",
        ]
    )

    tools_invoked = [
        "weather_api.get_live_air_quality",
        "drosophila_brain.run_drosophila_brain",
        "impact_engine.calculate_impact_delta",
        "knowledge_base.search_smog_playbook",
    ]
    _TELEMETRY_STATS["tool_calls_executed"] += len(tools_invoked)

    response = ActionPlanResponse(
        headline=headline,
        drosophila_interpretation=bio_interp,
        routine_schedule=_build_local_routine_schedule(air, brain, profile),
        action_cards=_build_action_cards(air, profile, chosen),
        community_playbook=community_playbook,
        impact_summary=impact,
        telemetry=GenAITelemetry(
            provider_used=active_provider_label,
            model_tier=model_tier,
            cache_hit=False,
            prompt_tokens_raw=raw_tok,
            prompt_tokens_compressed=comp_tok,
            compression_ratio_pct=ratio_pct,
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            tools_invoked=tools_invoked,
            grounding_sources=[d.citation for d in rag_docs],
        ),
    )
    _PLAN_CACHE[fp] = (now, response)
    return response


async def _gemini_tool_chat(
    api_key: str,
    model_name: str,
    req: ChatRequest,
    compact_ctx: str,
    history_str: str,
) -> tuple[str, list[str]]:
    """Run Gemini chat with function-calling support so the model invokes live Maruth tools."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    user_prompt = (
        f"LIVE_CONTEXT:\n{compact_ctx}\n\n"
        f"RECENT_CHAT:\n{history_str}\n\n"
        f"USER_QUESTION: {req.message}"
    )
    contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": user_prompt}]}]
    tools_called: list[str] = []

    async with httpx.AsyncClient(timeout=18.0) as client:
        for _ in range(2):
            body = {
                "systemInstruction": {"parts": [{"text": MARUTH_SYSTEM_PROMPT}]},
                "contents": contents,
                "tools": GEMINI_TOOL_DECLARATIONS,
                "generationConfig": {"temperature": 0.35, "maxOutputTokens": 650},
            }
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            candidate = data["candidates"][0]["content"]
            parts = candidate.get("parts", [])

            fn_calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not fn_calls:
                text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
                return text, tools_called

            contents.append(candidate)
            fn_responses = []
            for fc in fn_calls:
                t_name = fc["name"]
                t_args = fc.get("args", {})
                tools_called.append(t_name)
                result = _execute_tool_call(t_name, t_args, req.city_id, req.profile, req.selected_interventions)
                fn_responses.append(
                    {
                        "functionResponse": {
                            "name": t_name,
                            "response": {"result": result},
                        }
                    }
                )
            contents.append({"role": "user", "parts": fn_responses})

    return "Unable to complete Gemini response.", tools_called


async def _anthropic_chat(
    api_key: str,
    req: ChatRequest,
    compact_ctx: str,
    history_str: str,
) -> str:
    import anthropic

    def _sync_call() -> str:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=650,
            temperature=0.35,
            system=MARUTH_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"LIVE_CONTEXT:\n{compact_ctx}\n\nRECENT_CHAT:\n{history_str}\n\nUSER_QUESTION: {req.message}",
                }
            ],
        )
        return msg.content[0].text

    return await asyncio.to_thread(_sync_call)


def _synthesize_local_chat_answer(
    req: ChatRequest,
    air: AirQualityReport,
    brain: DrosophilaBioSensorResult,
    impact: ImpactSummary,
    rag_docs: list[Any],
) -> str:
    """Grounded, structured fallback response using live telemetry, Nengo brain status, physics math, and BM25 RAG."""
    q = req.message.lower()
    vuln_str = ", ".join(req.profile.vulnerable_groups) if req.profile.vulnerable_groups else "your household"
    lines: list[str] = []

    if any(w in q for w in ("walk", "jog", "run", "outside", "school", "window", "ventilat", "time", "when")):
        best_win = ", ".join(air.safe_ventilation_windows[:2])
        lines.append(
            f"**Outdoor & Ventilation Timing for {air.city_name}** (Live PM2.5: **{air.pm2_5} ug/m3**, Drosophila Status: **{brain.status}**):"
        )
        if brain.status == "HIGH POLLUTION" or air.pm2_5 > 100:
            lines.append(
                f"- **Avoid outdoor exertion right now**—the 10-neuron Drosophila bio-sensor reads `{brain.neural_response}` (decoded `{brain.detected_pm2_5} ug/m3`), exceeding the 100 ug/m3 alert threshold."
            )
            lines.append(f"- **Best ventilation / errand window**: **{best_win}** when daytime thermal mixing eases the {air.inversion_risk} inversion.")
        else:
            lines.append(
                f"- **Moderate caution**: Current PM2.5 is {air.pm2_5} ug/m3 (`{brain.status}`). Keep heavy exertion brief and favor **{best_win}**."
            )
        lines.append(f"- For **{vuln_str}**, wear a snug N95/FFP2 mask whenever walking along traffic corridors.")
    elif any(w in q for w in ("purifier", "hepa", "box fan", "corsi", "seal", "indoor", "room", "bedroom", "hack", "budget")):
        lines.append(
            f"**Indoor Clean-Air Setup for Your {int(req.profile.room_volume_m3)} m3 Space ({req.profile.home_sealing} sealing):**"
        )
        lines.append(
            f"- With your current choices, indoor PM2.5 drops from **{impact.baseline_indoor_pm2_5} ug/m3** to **{impact.projected_indoor_pm2_5} ug/m3** (**-{impact.indoor_reduction_pct}%**, avoiding **~{impact.cigarette_equivalents_avoided_week} cigarette-equivalents/week**)."
        )
        lines.append(
            "- **Zero-cost step today**: Seal door bottoms with a damp draft cloth, apply foam tape to sliding window tracks, and switch from dry sweeping to damp mopping."
        )
        lines.append(
            "- **Low-cost high-CADR hack (~Rs 1,650)**: Tape a MERV-13/HEPA filter panel onto the intake of a 16-inch box/table fan (~320 m3/h CADR) and run it in one closed bedroom."
        )
    elif any(w in q for w in ("cook", "gas", "wood", "fire", "commute", "car", "community", "neighbor", "impact", "co2")):
        lines.append(f"**Direct Personal & Neighborhood Impact in {air.city_name}:**")
        lines.append(
            f"- Your active lifestyle plan cuts **~{impact.community_pm25_emission_saved_g_day} g/day of primary PM2.5** and **~{impact.co2e_saved_kg_month} kg CO2e/month**."
        )
        lines.append(
            f"- Shifting boiling/simmering from `{req.profile.cooking_fuel}` to an electric kettle or induction stove reduces indoor kitchen NO2 & ultrafine particles while saving fuel cost."
        )
        lines.append(
            "- **Neighborhood multiplier**: Organize a zero-leaf-burn pact and provide warm jackets/thermos tea to night security guards so coal/wood bonfires stop under winter inversions."
        )
    else:
        lines.append(
            f"**Maruth Assessment for {air.city_name}** (US AQI **{air.us_aqi} — {air.aqi_category}**, Drosophila Bio-Sensor: **{brain.status}**):"
        )
        lines.append(
            f"- **Air & Gas Snapshot**: PM2.5 `{air.pm2_5} ug/m3`, PM10 `{air.pm10} ug/m3`, CO `{air.co} ug/m3`, NO2 `{air.no2} ug/m3` (Inversion Risk: **{air.inversion_risk}**)."
        )
        lines.append(
            f"- **Projected Indoor Shield**: Applying your selected habits reduces indoor exposure from **{impact.baseline_indoor_pm2_5} -> {impact.projected_indoor_pm2_5} ug/m3** (**-{impact.indoor_reduction_pct}%**) and avoids **{int(impact.daily_inhaled_pm25_avoided_ug)} ug/day** of inhaled soot for your {req.profile.household_size}-person home."
        )

    if rag_docs:
        top_doc = rag_docs[0]
        lines.append(f"\n*Grounded in {top_doc.title} ({top_doc.citation}):* {top_doc.content}")
    return "\n".join(lines)


async def stream_chat_reply(req: ChatRequest) -> AsyncIterator[str]:
    """Stream SSE events (`meta`, `tool`, `delta`, `done`) for responsive Maruth chat."""
    t0 = time.perf_counter()
    _TELEMETRY_STATS["total_requests"] += 1

    air = get_city_air_quality(req.city_id)
    brain = evaluate_drosophila_sensor(air)
    chosen = req.selected_interventions or get_default_interventions(req.profile)
    impact = calculate_impact_delta(air, req.profile, chosen)
    rag_docs = search_smog_playbook(f"{req.message} {air.city_name} {brain.status}", top_k=2)
    rag_snippets = [f"[{d.title}] {d.content}" for d in rag_docs]

    compact_ctx, raw_tok, comp_tok, ratio_pct = compress_context(air, brain, req.profile, impact, rag_snippets)
    history_str = compress_chat_history(req.history, max_recent=4)
    _TELEMETRY_STATS["tokens_saved_by_compression"] += max(0, raw_tok - comp_tok)

    provider_mode, resolved_key = _resolve_provider_and_key(req.api_provider, req.api_key)
    is_complex = len(req.message) > 140 or any(k in req.message.lower() for k in ("plan", "compare", "community", "why"))
    tools_used = [
        "weather_api.get_live_air_quality",
        "drosophila_brain.run_drosophila_brain",
        "impact_engine.calculate_impact_delta",
        "knowledge_base.search_smog_playbook",
    ]
    _TELEMETRY_STATS["tool_calls_executed"] += len(tools_used)

    yield f"event: meta\ndata: {json.dumps({'provider': provider_mode, 'compressed_tokens': comp_tok, 'compression_pct': ratio_pct})}\n\n"
    for tool_label in tools_used:
        yield f"event: tool\ndata: {json.dumps({'tool': tool_label})}\n\n"
        await asyncio.sleep(0.02)

    answer_text = ""
    used_provider_label = "Maruth Local RAG + Physics Engine"
    tier_used = "local_rag"

    if provider_mode == "gemini" and resolved_key:
        model_name = req.model_override or ("gemini-2.5-pro" if is_complex else "gemini-2.5-flash")
        try:
            answer_text, extra_tools = await _gemini_tool_chat(resolved_key, model_name, req, compact_ctx, history_str)
            tools_used.extend(extra_tools)
            used_provider_label = f"Google Gemini ({model_name})"
            tier_used = "reasoning" if "pro" in model_name else "fast"
        except Exception:
            answer_text = ""
    elif provider_mode == "anthropic" and resolved_key:
        try:
            answer_text = await _anthropic_chat(resolved_key, req, compact_ctx, history_str)
            used_provider_label = "Anthropic Claude (Haiku)"
            tier_used = "fast"
        except Exception:
            answer_text = ""

    if not answer_text:
        answer_text = _synthesize_local_chat_answer(req, air, brain, impact, rag_docs)
        used_provider_label = "Maruth Local RAG + Physics Engine"
        tier_used = "local_rag"

    # Stream token chunks smoothly to UI
    words = answer_text.split(" ")
    chunk_size = 5
    for idx in range(0, len(words), chunk_size):
        chunk = " ".join(words[idx : idx + chunk_size])
        if idx + chunk_size < len(words):
            chunk += " "
        yield f"event: delta\ndata: {json.dumps({'text': chunk})}\n\n"
        await asyncio.sleep(0.015)

    done_payload = {
        "provider_used": used_provider_label,
        "model_tier": tier_used,
        "tools_invoked": list(dict.fromkeys(tools_used)),
        "grounding_sources": [d.citation for d in rag_docs],
        "prompt_tokens_raw": raw_tok,
        "prompt_tokens_compressed": comp_tok,
        "compression_ratio_pct": ratio_pct,
        "output_tokens_est": estimate_tokens(answer_text),
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
