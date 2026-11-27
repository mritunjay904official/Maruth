"""Curated winter smog & IAQ scientific knowledge base with lightweight BM25/TF-IDF retrieval."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PlaybookDoc:
    doc_id: str
    title: str
    tags: tuple[str, ...]
    content: str
    citation: str


PLAYBOOK_DOCS: list[PlaybookDoc] = [
    PlaybookDoc(
        doc_id="kb_inversion_windows",
        title="Winter Boundary-Layer Inversion & Ventilation Timing",
        tags=("inversion", "ventilation", "windows", "morning", "evening", "bolpur", "kolkata", "delhi"),
        content=(
            "Cold winter nights create a radiation temperature inversion that traps PM2.5, CO, and NO2 in the lowest 50-150m. "
            "Outdoor PM2.5 commonly peaks between 20:00-09:00 and drops 30-45% between 13:00-16:00 when solar warming lifts the mixing layer. "
            "Open opposite-facing windows briefly during mid-afternoon for CO2 clearance, and keep frames sealed overnight."
        ),
        citation="WHO Urban Air Quality & Boundary-Layer Mixing Guidance",
    ),
    PlaybookDoc(
        doc_id="kb_corsi_rosenthal",
        title="DIY Corsi-Rosenthal Box Fan Air Scrubber Sizing",
        tags=("diy", "purifier", "hepa", "merv13", "box fan", "cadr", "budget", "indoor"),
        content=(
            "Taping a MERV-13 or H13 HEPA replacement filter tightly onto the intake side of a 400mm box/table fan delivers 280-350 m3/h CADR. "
            "In a 45 m3 sealed bedroom, that achieves 6+ air changes per hour (ACH), cutting indoor PM2.5 by 65-80% within 45 minutes. "
            "Seal every edge gap with duct tape to avoid air bypass."
        ),
        citation="Corsi-Rosenthal Foundation & ASHRAE Clean Air Room Protocol",
    ),
    PlaybookDoc(
        doc_id="kb_drosophila_biosensor",
        title="Drosophila Olfactory Ensemble Bio-Sensor Interpretation",
        tags=("drosophila", "nengo", "neural", "sensor", "pm2.5", "threshold", "high pollution"),
        content=(
            "Maruth's 10-neuron Nengo Drosophila olfactory model normalizes live PM2.5 (0-500 ug/m3 -> 0.0-1.0) and integrates firing over 5.0 seconds. "
            "When decoded ensemble output exceeds 100 ug/m3 (neural response > ~0.20), status switches to HIGH POLLUTION, triggering clean-room sealing, "
            "N95 outdoor masks, and suspension of vigorous outdoor exercise."
        ),
        citation="Maruth Bio-Inspired Nengo Olfactory Threshold Spec",
    ),
    PlaybookDoc(
        doc_id="kb_indoor_sources",
        title="Indoor Particle Spikes: Sweeping, Incense, Coils & Cooking",
        tags=("cooking", "incense", "mosquito coil", "mop", "broom", "kitchen", "lpg", "biomass", "no2"),
        content=(
            "Dry brooming re-suspends coarse and fine settled soot back into child breathing height; damp microfiber mopping cuts re-suspension. "
            "Burning one mosquito coil or stick of incense in a closed room can spike PM2.5 above 250 ug/m3. "
            "Shifting tea/boiling to an electric kettle or induction stove cuts indoor NO2 and ultrafine soot by up to 60%."
        ),
        citation="Indoor Air Quality Source Control & Clean Cooking Studies",
    ),
    PlaybookDoc(
        doc_id="kb_vulnerable_groups",
        title="Protecting Children, Elderly & Asthma/COPD Households",
        tags=("children", "infants", "elderly", "asthma", "copd", "mask", "n95", "health", "lungs"),
        content=(
            "Children breathe more air per kg of body weight than adults and have developing alveoli; elders and asthma/COPD patients face acute inflammation from PM2.5 and NO2. "
            "Create one sealed 'Clean Air Sanctuary' bedroom with continuous HEPA/DIY filtration, keep rescue inhalers accessible, and avoid early-morning walks when AQI > 150."
        ),
        citation="Pediatric & Respiratory Smog Protection Checklist",
    ),
    PlaybookDoc(
        doc_id="kb_community_no_burn",
        title="Community Zero-Burn & School No-Idling Playbook",
        tags=("community", "rwa", "school", "carpool", "leaf burning", "bonfire", "bolpur", "kolkata", "delhi"),
        content=(
            "Backyard dry-leaf burning, trash fires, and guard winter wood fires emit intense localized PM2.5 plumes under calm winter inversions. "
            "Community actions with highest neighborhood impact: (1) compost dry leaves instead of burning, (2) provide warm jackets/thermoses to night guards, "
            "(3) enforce engine-off school drop-off zones, and (4) organize 3-family commuter carpools."
        ),
        citation="Urban Neighborhood Clean-Air Collective Toolkit",
    ),
    PlaybookDoc(
        doc_id="kb_masks_fit",
        title="Respirator Selection & Proper Fit During Severe Smog",
        tags=("mask", "n95", "kn95", "ffp2", "cloth", "surgical", "commute"),
        content=(
            "Cloth and loose surgical masks leak 50-70% of 2.5-micron aerosols around the cheeks and nose bridge. "
            "Use NIOSH N95, FFP2, or well-sealed KN95 respirators with a moldable metal nose clip whenever PM2.5 exceeds 55 ug/m3, "
            "and avoid exhalation-valve masks if protecting vulnerable household members from respiratory droplets."
        ),
        citation="NIOSH / WHO Particle Filtration Guidance",
    ),
]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", text.lower())


_DOC_TOKENS = [Counter(_tokenize(f"{d.title} {' '.join(d.tags)} {d.content}")) for d in PLAYBOOK_DOCS]
_DF: Counter[str] = Counter()
for tok_counts in _DOC_TOKENS:
    for term in tok_counts:
        _DF[term] += 1
_AVG_LEN = sum(sum(c.values()) for c in _DOC_TOKENS) / max(1, len(_DOC_TOKENS))


def search_smog_playbook(query: str, top_k: int = 3) -> list[PlaybookDoc]:
    """BM25 retrieval over the curated winter smog & IAQ knowledge base."""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return PLAYBOOK_DOCS[:top_k]

    n_docs = len(PLAYBOOK_DOCS)
    k1 = 1.4
    b = 0.75
    scored: list[tuple[float, PlaybookDoc]] = []

    for doc, tf_counter in zip(PLAYBOOK_DOCS, _DOC_TOKENS):
        doc_len = sum(tf_counter.values())
        score = 0.0
        for term in q_tokens:
            tf = tf_counter.get(term, 0)
            if tf == 0:
                continue
            df = _DF.get(term, 1)
            idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
            denom = tf + k1 * (1.0 - b + b * (doc_len / _AVG_LEN))
            score += idf * (tf * (k1 + 1.0)) / denom
            if term in doc.tags:
                score += 0.35
        scored.append((score, doc))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = [doc for sc, doc in scored[:top_k] if sc > 0]
    return top if top else PLAYBOOK_DOCS[:top_k]
