const state = {
  cityId: "bolpur",
  customCityQuery: null,
  presets: [],
  airQuality: null,
  drosophila: null,
  plan: null,
  selectedInterventions: [],
  chatHistory: [],
  apiProvider: localStorage.getItem("maruth_provider") || "auto",
  apiKey: localStorage.getItem("maruth_api_key") || "",
};

const $ = (id) => document.getElementById(id);

function readProfileFromForm() {
  const vuln = Array.from(document.querySelectorAll("#vulnChips .chip.active")).map((c) => c.dataset.val);
  return {
    city_id: state.cityId,
    household_size: Number($("householdSize").value) || 4,
    vulnerable_groups: vuln,
    home_sealing: $("homeSealing").value,
    room_volume_m3: Number($("roomVolume").value) || 45,
    cooking_fuel: $("cookingFuel").value,
    heating_source: $("heatingSource").value,
    commute_mode: $("commuteMode").value,
    daily_commute_km: Number($("commuteKm").value) || 14,
    budget_tier: $("budgetTier").value,
    has_hepa_purifier: $("hasHepa").checked,
  };
}

async function init() {
  bindUIEvents();
  $("apiProviderSelect").value = state.apiProvider;
  $("apiKeyInput").value = state.apiKey;
  await loadPresets();
  await loadFullDashboard(false);
}

function bindUIEvents() {
  $("refreshBtn").addEventListener("click", () => loadFullDashboard(true));
  $("regeneratePlanBtn").addEventListener("click", () => loadFullDashboard(false, true));
  $("citySearchBtn").addEventListener("click", handleCitySearch);
  $("citySearchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleCitySearch();
  });

  document.querySelectorAll("#vulnChips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      chip.classList.toggle("active");
      loadFullDashboard(false, true);
    });
  });

  ["householdSize", "roomVolume", "homeSealing", "budgetTier", "cookingFuel", "heatingSource", "commuteMode", "commuteKm", "hasHepa"].forEach((id) => {
    $(id).addEventListener("change", () => loadFullDashboard(false, true));
  });

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });

  $("stressPmSlider").addEventListener("input", (e) => {
    $("stressPmLabel").textContent = `${e.target.value} ug/m3`;
  });

  $("runBioTestBtn").addEventListener("click", async () => {
    const val = Number($("stressPmSlider").value);
    await rerunBioSensor(val);
  });

  $("resetBioLiveBtn").addEventListener("click", async () => {
    $("stressPmLabel").textContent = "Live City";
    await rerunBioSensor(null);
  });

  $("copyPlaybookBtn").addEventListener("click", () => {
    const items = state.plan?.community_playbook || [];
    const text = `Maruth Clean-Air Community Brief (${state.airQuality?.city_name || ""}):\n` + items.map((x, i) => `${i + 1}. ${x}`).join("\n");
    navigator.clipboard?.writeText(text);
    $("copyPlaybookBtn").textContent = "Copied!";
    setTimeout(() => ($("copyPlaybookBtn").textContent = "Copy Shareable Brief"), 1800);
  });

  document.querySelectorAll(".qp-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("chatInput").value = btn.dataset.q;
      sendChatMessage();
    });
  });

  $("chatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    sendChatMessage();
  });

  $("openSettingsBtn").addEventListener("click", async () => {
    $("settingsModal").classList.remove("hidden");
    await refreshTelemetryStats();
  });
  $("closeSettingsBtn").addEventListener("click", () => $("settingsModal").classList.add("hidden"));
  $("saveSettingsBtn").addEventListener("click", () => {
    state.apiProvider = $("apiProviderSelect").value;
    state.apiKey = $("apiKeyInput").value.trim();
    localStorage.setItem("maruth_provider", state.apiProvider);
    localStorage.setItem("maruth_api_key", state.apiKey);
    $("settingsModal").classList.add("hidden");
    loadFullDashboard(false);
  });
}

async function loadPresets() {
  const res = await fetch("/api/presets");
  const data = await res.json();
  state.presets = data.presets || [];
  renderPresetPills();
}

function renderPresetPills() {
  const wrap = $("presetPills");
  wrap.innerHTML = "";
  state.presets.forEach((p) => {
    const btn = document.createElement("button");
    btn.className = `preset-pill ${p.id === state.cityId && !state.customCityQuery ? "active" : ""}`;
    btn.textContent = p.name;
    btn.addEventListener("click", () => {
      state.cityId = p.id;
      state.customCityQuery = null;
      renderPresetPills();
      loadFullDashboard(false, true);
    });
    wrap.appendChild(btn);
  });
}

async function handleCitySearch() {
  const q = $("citySearchInput").value.trim();
  if (!q) return;
  state.customCityQuery = q;
  renderPresetPills();
  await loadFullDashboard(false, true);
}

async function loadFullDashboard(forceRefresh = false, resetSelection = false) {
  $("planHeadline").textContent = "Running Open-Meteo telemetry, 10-neuron Nengo simulation & GenAI planner...";
  const profile = readProfileFromForm();
  const payload = {
    city_id: state.cityId,
    custom_city_query: state.customCityQuery,
    profile,
    selected_interventions: resetSelection || state.selectedInterventions.length === 0 ? null : state.selectedInterventions,
    api_provider: state.apiProvider,
    api_key: state.apiKey || null,
    force_refresh: forceRefresh,
  };

  const res = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data.error) {
    $("planHeadline").textContent = `Error: ${data.error}`;
    return;
  }

  state.airQuality = data.air_quality;
  state.cityId = data.air_quality.city_id;
  state.drosophila = data.drosophila;
  state.plan = data.plan;
  if (resetSelection || state.selectedInterventions.length === 0) {
    state.selectedInterventions = data.default_selected || [];
  }

  renderAirQuality(data.air_quality);
  renderDrosophila(data.drosophila);
  renderPlan(data.plan);
  renderImpact(data.plan.impact_summary);
}

function renderAirQuality(aq) {
  $("citySubtitle").textContent = `${aq.city_name}, ${aq.region} (${aq.lat.toFixed(2)}, ${aq.lon.toFixed(2)})`;
  const sourceMap = {
    live_open_meteo: "Live Open-Meteo",
    cached_open_meteo: "Cached Open-Meteo",
    regional_fallback: "Regional Baseline",
  };
  $("dataSourceBadge").textContent = sourceMap[aq.data_source] || aq.data_source;

  $("aqiValue").textContent = aq.us_aqi;
  $("aqiCategory").textContent = aq.aqi_category;
  $("aqiBadge").style.borderColor = aq.aqi_color;
  $("aqiBadge").style.background = `${aq.aqi_color}24`;

  $("pm25Val").textContent = aq.pm2_5;
  $("pm10Val").textContent = aq.pm10;
  $("coVal").textContent = aq.co;
  $("no2Val").textContent = aq.no2;

  $("inversionRisk").textContent = `Inversion Risk: ${aq.inversion_risk}`;
  $("weatherStats").textContent = `Wind: ${aq.wind_kmh ?? "--"} km/h • Temp: ${aq.temp_c ?? "--"} °C`;
  $("inversionText").textContent = aq.inversion_explanation;
  $("safeWindowsLabel").textContent = `Best Airing: ${aq.safe_ventilation_windows.slice(0, 2).join(", ")}`;

  if ($("stressPmLabel").textContent === "Live City") {
    $("stressPmSlider").value = Math.min(450, Math.max(10, Math.round(aq.pm2_5)));
  }

  drawHourlyChart(aq.hourly_profile || []);
}

function drawHourlyChart(points) {
  const svg = $("hourlyChart");
  if (!points.length) {
    svg.innerHTML = "";
    return;
  }
  const w = 560, h = 155, padL = 34, padR = 14, padT = 14, padB = 26;
  const maxPm = Math.max(120, ...points.map((p) => p.pm2_5)) * 1.1;
  const stepX = (w - padL - padR) / Math.max(1, points.length - 1);

  const coords = points.map((p, i) => {
    const x = padL + i * stepX;
    const y = h - padB - ((p.pm2_5 / maxPm) * (h - padT - padB));
    return { x, y, ...p };
  });

  const pathD = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
  const areaD = `${pathD} L ${coords[coords.length - 1].x.toFixed(1)} ${h - padB} L ${coords[0].x.toFixed(1)} ${h - padB} Z`;

  let html = `
    <defs>
      <linearGradient id="pmGrad" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#f43f5e" stop-opacity="0.45"/>
        <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.04"/>
      </linearGradient>
    </defs>
    <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="rgba(148,163,184,0.3)" />
    <text x="4" y="${padT + 8}" fill="#94a3b8" font-size="10">${Math.round(maxPm)}</text>
    <text x="8" y="${h - padB}" fill="#94a3b8" font-size="10">0</text>
    <path d="${areaD}" fill="url(#pmGrad)" />
    <path d="${pathD}" fill="none" stroke="#38bdf8" stroke-width="2.5" />
  `;

  coords.forEach((c) => {
    const color = c.ventilation_safe ? "#34d399" : "#f43f5e";
    if (c.ventilation_safe) {
      html += `<rect x="${(c.x - 14).toFixed(1)}" y="${padT}" width="28" height="${h - padT - padB}" fill="rgba(52,211,153,0.12)" rx="4" />`;
    }
    html += `<circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="4.2" fill="${color}" stroke="#0f172a" stroke-width="1.5" />`;
    html += `<text x="${c.x.toFixed(1)}" y="${h - 8}" text-anchor="middle" fill="#94a3b8" font-size="10">${c.hour_label}</text>`;
  });
  svg.innerHTML = html;
}

function renderDrosophila(bio) {
  const pill = $("bioStatusPill");
  pill.textContent = bio.status;
  pill.classList.toggle("high", bio.status === "HIGH POLLUTION");

  $("neuralResponseVal").textContent = bio.neural_response.toFixed(4);
  $("detectedPm25Val").textContent = `${bio.detected_pm2_5} ug/m3`;
  $("firingRateVal").textContent = bio.trace ? `${bio.trace.mean_firing_rate_hz} Hz` : "--";
  $("bioInterpText").textContent = bio.alert_summary;
  $("simModeBadge").textContent = bio.simulation_mode;

  if (bio.trace) {
    drawNengoTrace(bio.trace);
    renderNeuronBars(bio.trace.neuron_rates_hz || []);
  }
}

function drawNengoTrace(trace) {
  const svg = $("nengoTraceChart");
  const times = trace.time_s || [];
  const inp = trace.input_signal || [];
  const neu = trace.neural_signal || [];
  if (!times.length) {
    svg.innerHTML = "";
    return;
  }

  const w = 560, h = 130, padL = 32, padR = 14, padT = 12, padB = 22;
  const maxY = Math.max(0.35, ...inp, ...neu) * 1.15;
  const toX = (i) => padL + (i / Math.max(1, times.length - 1)) * (w - padL - padR);
  const toY = (v) => h - padB - (Math.max(0, v) / maxY) * (h - padT - padB);

  const inpPath = inp.map((v, i) => `${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)} ${toY(v).toFixed(1)}`).join(" ");
  const neuPath = neu.map((v, i) => `${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)} ${toY(v).toFixed(1)}`).join(" ");
  const threshY = toY(0.2);

  svg.innerHTML = `
    <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="rgba(148,163,184,0.3)" />
    <line x1="${padL}" y1="${threshY.toFixed(1)}" x2="${w - padR}" y2="${threshY.toFixed(1)}" stroke="rgba(244,63,94,0.45)" stroke-dasharray="4 4" />
    <text x="${w - padR - 4}" y="${(threshY - 4).toFixed(1)}" text-anchor="end" fill="#fda4af" font-size="9">100 ug/m3 threshold (0.20)</text>
    <path d="${inpPath}" fill="none" stroke="#94a3b8" stroke-width="1.8" stroke-dasharray="5 3" />
    <path d="${neuPath}" fill="none" stroke="#38bdf8" stroke-width="2.4" />
    <text x="${padL}" y="${h - 6}" fill="#94a3b8" font-size="9">0.0s</text>
    <text x="${w - padR}" y="${h - 6}" text-anchor="end" fill="#94a3b8" font-size="9">5.0s Nengo Sim</text>
  `;
}

function renderNeuronBars(rates) {
  const wrap = $("neuronBars");
  const maxRate = Math.max(60, ...rates);
  wrap.innerHTML = "";
  rates.forEach((r, idx) => {
    const col = document.createElement("div");
    col.className = "n-col";
    const pct = Math.max(8, Math.round((r / maxRate) * 100));
    col.innerHTML = `
      <div class="n-bar" style="height:${pct}%" title="Neuron ${idx}: ${r} Hz"></div>
      <span class="n-lbl">N${idx}</span>
    `;
    wrap.appendChild(col);
  });
}

async function rerunBioSensor(overridePm25) {
  const res = await fetch("/api/biosensor", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city_id: state.cityId,
      override_pm25: overridePm25,
      force_rerun: true,
    }),
  });
  const data = await res.json();
  if (data.drosophila) {
    renderDrosophila(data.drosophila);
  }
}

function renderPlan(plan) {
  $("planHeadline").textContent = plan.headline;
  $("providerPill").textContent = plan.telemetry.provider_used;
  $("compressionMetric").textContent = `-${plan.telemetry.compression_ratio_pct}%`;
  $("cacheMetric").textContent = plan.telemetry.cache_hit ? "HIT" : "FRESH";
  $("tierMetric").textContent = plan.telemetry.model_tier.toUpperCase();

  // Render daily routine slots
  const rtWrap = $("routineTimeline");
  rtWrap.innerHTML = "";
  (plan.routine_schedule || []).forEach((slot) => {
    const el = document.createElement("div");
    el.className = "routine-slot";
    el.innerHTML = `
      <div class="slot-head">
        <strong>${slot.time_window}</strong>
        <span class="risk-tag risk-${slot.smog_risk}">${slot.smog_risk}</span>
      </div>
      <div style="font-weight:600;margin-bottom:4px;">${slot.activity}</div>
      <p style="color:#cbd5e1;">${slot.recommendation}</p>
      <div class="slot-impact">${slot.impact_note}</div>
    `;
    rtWrap.appendChild(el);
  });

  // Render action cards across 3 pillars
  const routineContainer = $("routineCards");
  const iaqContainer = $("iaqCards");
  const susContainer = $("sustainableCards");
  routineContainer.innerHTML = "";
  iaqContainer.innerHTML = "";
  susContainer.innerHTML = "";

  const selectedSet = new Set(state.selectedInterventions);
  (plan.action_cards || []).forEach((card) => {
    const isSel = selectedSet.has(card.intervention_id);
    const el = document.createElement("div");
    el.className = `action-card ${isSel ? "selected" : ""}`;
    el.innerHTML = `
      <div class="ac-top">
        <div>
          <span class="tiny-tag">${card.priority}</span>
          <div class="ac-title" style="margin-top:4px;">${card.title}</div>
        </div>
        <label class="ac-toggle">
          <input type="checkbox" data-id="${card.intervention_id}" ${isSel ? "checked" : ""} />
          <span>Active</span>
        </label>
      </div>
      <div class="ac-impact-badge">${card.direct_impact_summary}</div>
      <p class="ac-why"><strong>Why it works:</strong> ${card.why_it_works}</p>
      <ol class="ac-steps">${card.steps.map((s) => `<li>${s}</li>`).join("")}</ol>
      <div class="ac-footer">
        <span>${card.tailored_guidance.slice(0, 72)}${card.tailored_guidance.length > 72 ? "..." : ""}</span>
        <strong>${card.monthly_cost_note}</strong>
      </div>
    `;

    el.querySelector("input[type='checkbox']").addEventListener("change", (e) => {
      toggleIntervention(card.intervention_id, e.target.checked, el);
    });

    if (card.pillar === "routine") routineContainer.appendChild(el);
    else if (card.pillar === "iaq_hack") iaqContainer.appendChild(el);
    else susContainer.appendChild(el);
  });

  const cpList = $("communityPlaybookList");
  cpList.innerHTML = (plan.community_playbook || []).map((item) => `<li>${item}</li>`).join("");
}

async function toggleIntervention(id, enabled, cardEl) {
  if (enabled && !state.selectedInterventions.includes(id)) {
    state.selectedInterventions.push(id);
  } else if (!enabled) {
    state.selectedInterventions = state.selectedInterventions.filter((x) => x !== id);
  }
  cardEl.classList.toggle("selected", enabled);

  const res = await fetch("/api/impact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city_id: state.cityId,
      profile: readProfileFromForm(),
      selected_interventions: state.selectedInterventions,
    }),
  });
  const data = await res.json();
  if (data.impact) renderImpact(data.impact);
}

function renderImpact(imp) {
  const maxVal = Math.max(imp.outdoor_pm2_5, imp.baseline_indoor_pm2_5, 50);
  $("barOutdoor").style.width = `${Math.min(100, (imp.outdoor_pm2_5 / maxVal) * 100)}%`;
  $("barBaseIn").style.width = `${Math.min(100, (imp.baseline_indoor_pm2_5 / maxVal) * 100)}%`;
  $("barProjIn").style.width = `${Math.min(100, (imp.projected_indoor_pm2_5 / maxVal) * 100)}%`;

  $("valOutdoor").textContent = `${imp.outdoor_pm2_5} ug/m3`;
  $("valBaseIn").textContent = `${imp.baseline_indoor_pm2_5} ug/m3`;
  $("valProjIn").textContent = `${imp.projected_indoor_pm2_5} ug/m3`;

  $("riskTransitionBadge").textContent = `${imp.health_risk_tier_before} -> ${imp.health_risk_tier_after}`;
  $("kpiIndoorCut").textContent = `-${imp.indoor_reduction_pct}%`;
  $("kpiInhaledCut").textContent = `${Math.round(imp.daily_inhaled_pm25_avoided_ug)} ug/day avoided`;
  $("kpiCigs").textContent = `-${imp.cigarette_equivalents_avoided_week}`;
  $("kpiPmSaved").textContent = `${imp.community_pm25_emission_saved_g_day} g/day`;
  $("kpiCo2Saved").textContent = `${imp.co2e_saved_kg_month} kg CO2e/mo`;

  const net = imp.net_monthly_cost_delta_inr;
  $("kpiCost").textContent = net <= 0 ? `Save Rs ${Math.abs(Math.round(net))}/mo` : `+Rs ${Math.round(net)}/mo`;
  $("kpiUpfront").textContent = `Upfront: Rs ${Math.round(imp.upfront_cost_total_inr)}`;

  $("causalList").innerHTML = (imp.causal_breakdown || []).map((c) => `<li>${c}</li>`).join("");
}

async function sendChatMessage() {
  const text = $("chatInput").value.trim();
  if (!text) return;
  $("chatInput").value = "";

  appendChatMsg("user", text);
  const assistantBody = appendChatMsg("assistant", "Thinking...");
  $("chatToolsBadge").textContent = "Calling tools...";

  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: text,
      city_id: state.cityId,
      profile: readProfileFromForm(),
      selected_interventions: state.selectedInterventions,
      history: state.chatHistory.slice(-8),
      api_provider: state.apiProvider,
      api_key: state.apiKey || null,
    }),
  });

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let fullText = "";
  let currentEvent = "message";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        const payload = JSON.parse(line.slice(5).trim());
        if (currentEvent === "tool") {
          $("chatToolsBadge").textContent = `Tool: ${payload.tool}`;
        } else if (currentEvent === "delta") {
          fullText += payload.text;
          assistantBody.querySelector(".msg-body").textContent = fullText;
          $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
        } else if (currentEvent === "done") {
          $("chatToolsBadge").textContent = `${payload.provider_used} • -${payload.compression_ratio_pct}% tokens`;
          const toolsEl = document.createElement("div");
          toolsEl.className = "msg-tools";
          toolsEl.textContent = `Tools: ${payload.tools_invoked.join(", ")} | Latency: ${payload.latency_ms}ms`;
          assistantBody.appendChild(toolsEl);
        }
      }
    }
  }

  state.chatHistory.push({ role: "user", content: text }, { role: "assistant", content: fullText });
}

function appendChatMsg(role, content) {
  const wrap = document.createElement("div");
  wrap.className = `chat-msg ${role}`;
  wrap.innerHTML = `<div class="msg-role">${role === "user" ? "You" : "Maruth"}</div><div class="msg-body"></div>`;
  wrap.querySelector(".msg-body").textContent = content;
  $("chatMessages").appendChild(wrap);
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  return wrap;
}

async function refreshTelemetryStats() {
  const res = await fetch("/api/telemetry");
  const data = await res.json();
  const s = data.optimization_stats || {};
  $("tTotalReq").textContent = s.total_requests ?? 0;
  $("tCacheHits").textContent = s.cache_hits ?? 0;
  $("tTokComp").textContent = s.tokens_saved_by_compression ?? 0;
  $("tTokCache").textContent = s.tokens_saved_by_cache ?? 0;
  $("tTools").textContent = s.tool_calls_executed ?? 0;
}

init();
