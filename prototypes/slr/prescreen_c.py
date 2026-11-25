"""SLR pre-screening of supplementary search C (``out/supplementary_C.csv``), 24 November 2026.

A PRE-screen by Claude for the author to check, not the final screening. Same criteria and conventions as
``prescreen.py`` (thesis Section 3.2): the keyword triage of ``prescreen.py`` first (a record without both a
language-model term and an energy term cannot meet I3 with I2), then the titles and abstracts of the remaining 58
records were read. Building HVAC control by a language model counts as I2 (buildings), as in the main set; grid,
market and public-charging studies are excluded (E1); question answering, explanation, diagnosis and data generation
without control are excluded (E2); reviews are kept as background. One record that fails the keyword triage (S0033)
is kept as LQ3 background on purpose.

Re-running overwrites the decision and reason columns of ``out/supplementary_C.csv`` only.

    uv run python prototypes/slr/prescreen_c.py
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from prescreen import EN, LM

OUT = Path(__file__).parent / "out"

INCLUDE = {
    "S0113": "LLMs translate user preferences into optimisation constraints for home appliances (Sanguinetti et al.; LQ1)",
    "S0121": "LLM agents propose and code control logic for a residential PV-battery system, near the LP optimum (LQ2)",
    "S0030": "EnergyBridge: household energy management benchmark with agents and household authorisation (LQ1)",
    "S0079": "LLMs as mutation operators evolving control policies for residential EV charging and V2G (LQ2)",
    "S0046": "ThermoLLM: LLM-based multi-zone HVAC control (buildings)",
    "S0069": "hierarchical LLM and RL control of building HVAC",
    "S0039": "open-weight reasoning model fine-tuned with verifiable rewards for building thermal storage control (LQ3)",
    # author's decision 24 Nov 2026 (was unsure: EV charging, home or station?)
    "S0131": "three LLM agents turn voice requests into an optimisation problem and solve it, EV charging (LQ1)",
    # author's decisions 24 Nov 2026 (were unsure)
    "S0020": "LLM turns user intent into bounded parameters under a physics supervisor (pattern for LQ1 checks); EV "
             "driving, not home energy",
    "S0140": "LLM simulates occupant feedback for HVAC control in a human-in-the-loop system (method, like R0007)",
    # author's decision 24 Nov 2026 (was unsure; fails the keyword triage, no energy objective)
    "S0033": "LQ3 background: on-device LLM agent defers uncertain actions to a cloud model (fallback design), "
             "no energy objective",
}  # fmt: skip
UNSURE: dict[str, str] = {}  # S0020, S0140 included and S0036 excluded by the author, 24 Nov 2026
LQ3_BACKGROUND: dict[str, str] = {}  # S0033 moved to INCLUDE by the author
BACKGROUND = {
    "S0023": "systematic review of 66 LLM studies for HVAC operations (kept as background; snowball its studies)",
}  # fmt: skip
EXCLUDE = {
    # same authors (Jin, Sel, Hardeep, Yin) and method; author's decision 24 Nov 2026: keep the published version
    "S0146": "duplicate: arXiv preprint 2308.10380 of R0696 (IEEE SmartGridComm 2024), published version kept",
    # author's decision 24 Nov 2026 (was unsure)
    "S0036": "LLM agents as prosumers drawing on a shared energy reserve: coordination game study, not household energy "
             "management",
    "S0024": "community peer-to-peer market level (E1); open-weight LLM sets market bounds",
    "S0090": "position paper on foundation models and smart grids, grid level (E1)",
    "S0097": "power grid control (E1)",
    "S0099": "distribution network dispatch modelling (E1); related natural-language-to-optimisation stream",
    "S0106": "peer-to-peer market fairness (E1)",
    "S0021": "public charging stations and grid (E1)",
    "S0112": "public charging station recommendation, no control (E1, E2)",
    "S0119": "EV smart charging with an LLM as a sequence model, not interpreting requirements or controlling (I3)",
    "S0128": "simulation of EV taxi drivers' charging behaviour, no control (I3)",
    "S0065": "geo-spatial question answering about EV charging (E2)",
    "S0134": "question answering over a household electricity digital twin (E2)",
    "S0103": "explanations of building energy use, no control (E2)",
    "S0085": "HVAC anomaly detection, no control (E2)",
    "S0091": "HVAC fault diagnosis, no control (E2)",
    "S0068": "LLM used for occupancy sensing, not for requirements or control (I3)",
    "S0062": "nudging architecture with a residential energy proof of concept, no control (E2)",
    "S0120": "LLM generates household energy data, no control (I3)",
    "S0080": "survey of battery technologies (outside scope)",
    "S0115": "small language models for edge devices in general, not energy management",
    "S0087": "federated training of on-device language models (language-model computing)",
    "S0137": "energy use of AI systems (language-model computing)",
    "S0150": "hardware for transformer inference (language-model computing)",
    "S0022": "LLM serving infrastructure (language-model computing)",
    "S0015": "data-centre thermal planning (language-model computing)",
}  # fmt: skip


def main() -> None:
    path = OUT / "supplementary_C.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for r in rows:
        text = r["title"] + " " + r["abstract"]
        i = r["id"]
        if i in INCLUDE:
            r["decision"], r["reason"] = "include", INCLUDE[i]
        elif i in UNSURE:
            r["decision"], r["reason"] = "unsure", UNSURE[i]
        elif i in LQ3_BACKGROUND:
            r["decision"], r["reason"] = "unsure", LQ3_BACKGROUND[i]
        elif i in BACKGROUND:
            r["decision"], r["reason"] = "exclude", "review or position paper (kept as background): " + BACKGROUND[i]
        elif i in EXCLUDE:
            r["decision"] = "duplicate" if EXCLUDE[i].startswith("duplicate") else "exclude"
            r["reason"] = EXCLUDE[i]
        elif not (LM.search(text) and EN.search(text)):
            r["decision"], r["reason"] = "exclude", "keyword triage: no language-model and energy terms together"
        else:
            r["decision"], r["reason"] = "exclude", "outside scope: not a language model in home or building energy management"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(Counter(r["decision"] for r in rows))
    print(Counter(r["reason"].split(":")[0] if r["reason"].startswith(("keyword", "outside")) else "listed"
                  for r in rows if r["decision"] == "exclude"))  # fmt: skip
    listed = set(INCLUDE) | set(UNSURE) | set(LQ3_BACKGROUND) | set(BACKGROUND) | set(EXCLUDE)
    missing = listed - {r["id"] for r in rows}
    assert not missing, missing


if __name__ == "__main__":
    main()
