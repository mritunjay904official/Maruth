# Maruth — GenAI Winter Smog & Drosophila Bio-Sensor Assistant

**Maruth** is a GenAI-powered web dashboard that helps families and communities navigate severe winter smog and urban air pollution. It combines real-time pollutant telemetry (`weather_api.py`), a 10-neuron Nengo *Drosophila* olfactory neural bio-sensor (`drosophila_brain.py`), a deterministic indoor air-quality physics & emissions impact engine, and an optimized multi-provider GenAI orchestrator.

---

## Key Capabilities

- **Live Pollutant & Gas Telemetry (`weather_api.py`)**
  - Fetches real-time **$\text{PM}_{2.5}$**, **$\text{PM}_{10}$**, **$\text{CO}$**, and **$\text{NO}_2$** from Open-Meteo.
  - Calculates US EPA AQI, winter boundary-layer inversion risk (wind + temperature), and 24-hour **Safe Ventilation Windows**.
  - Includes regional presets (**Bolpur (Santiniketan)**, **Kolkata**, **Delhi NCR**, Patna, Lahore, Beijing, Salt Lake City) plus custom city search via Open-Meteo Geocoding and automatic offline baseline fallback.
- **10-Neuron *Drosophila* Olfactory Bio-Sensor (`drosophila_brain.py`)**
  - Scales live $\text{PM}_{2.5}$ (`0–500 µg/m³ → 0.0–1.0`) into a 10-neuron `nengo.Ensemble` over a 5.0-second spiking simulation.
  - Surfaces `neural_response`, `detected_pm2_5`, `HIGH POLLUTION` (`> 100 µg/m³`) vs. `NORMAL` status, per-neuron firing rates (`N0–N9` in Hz), live probe waveforms, and an interactive custom $\text{PM}_{2.5}$ stimulus slider.
- **GenAI Optimization & Tool-Grounded Architecture**
  - **Tool Calling**: Grounds LLM answers in `weather_api.get_live_air_quality`, `drosophila_brain.run_drosophila_brain`, `impact_engine.calculate_impact_delta`, and `knowledge_base.search_smog_playbook` (BM25 RAG).
  - **Prompt Compression & Sliding-Window Memory**: Serializes household & environmental state into a high-density digest to reduce input token usage.
  - **Model-Tier Routing**: Routes lightweight requests to fast models (`gemini-2.5-flash` / `claude-3-5-haiku-latest`) and high-risk/vulnerable-household plans to reasoning models (`gemini-2.5-pro`), with an out-of-the-box **Local RAG + Physics Engine** fallback when no API key is configured.
  - **Two-Layer Caching & SSE Streaming**: 15-minute environmental TTL cache, household-fingerprint plan cache, and Server-Sent Events streaming chat with live optimization telemetry.
- **Direct Choice Impact Explainer**
  - Single-zone indoor $\text{PM}_{2.5}$ mass-balance & CADR physics model:
    $$C_{\text{in}} = \frac{P \cdot \text{AER} \cdot C_{\text{out}} + S_{\text{in}} / V}{\text{AER} + k_{\text{dep}} + \text{CADR} / V}$$
  - Toggle low-emission daily routines, DIY/HEPA indoor air hacks (e.g., Corsi-Rosenthal CR-Box, door/window weatherstripping, wet mopping), and sustainable community swaps (induction cooking, zero-burn warmth, transit/carpool) to see live indoor $\text{PM}_{2.5}$ drops, cigarette-equivalents avoided, $\text{g PM}_{2.5}\text{/day}$ & $\text{kg CO}_2\text{e/month}$ saved, monthly ₹ cost delta, and plain-language causal explanations.

---

## Project Structure

```text
├── app.py                          # Tornado async REST + SSE server & static host
├── weather_api.py                  # Open-Meteo live PM2.5, PM10, CO, NO2 client
├── drosophila_brain.py             # 10-neuron Nengo Drosophila olfactory simulation
├── requirements.txt                # Python dependencies
├── maruth/
│   ├── schemas.py                  # Pydantic schemas for telemetry, plans & chat
│   ├── air_quality.py              # Regional presets, geocoding, inversion risk & TTL cache
│   ├── bio_sensor.py               # Wrapper & trace caching for drosophila_brain.py
│   ├── impact_engine.py            # Indoor mass-balance, emissions & cost calculator
│   ├── knowledge_base.py           # Curated smog/IAQ playbook + BM25 retriever
│   ├── prompts.py                  # Compact prompt compression & Gemini tool declarations
│   └── genai_orchestrator.py       # Gemini / Anthropic / Local RAG router + SSE streaming
├── static/
│   ├── index.html                  # Maruth web dashboard
│   ├── styles.css                  # Responsive atmospheric UI styles
│   └── app.js                      # Interactive charts, Nengo trace SVG & SSE chat
└── tests/
    ├── test_modules_and_impact.py  # Unit tests for sensors, impact physics & RAG
    └── test_orchestrator_and_api.py # Tests for compression, caching & Tornado endpoints
```

---

## Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Dashboard
```bash
python app.py
```
Open **http://localhost:8000** in your browser.

> **Optional Live LLM Keys:** Click **AI Settings & Telemetry** in the top bar to enter a Google Gemini (`AIza...`) or Anthropic (`sk-ant-...`) API key, or set `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` in your environment. Without a key, Maruth automatically uses its **Local RAG + Physics Engine** so every dashboard feature works immediately.

### 3. Run Automated Tests
```bash
python -m unittest discover -s tests -v
```
