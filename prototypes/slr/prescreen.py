"""SLR pre-screening (title, with the abstract where a title is unclear) of ``out/screening.csv``, 11 November 2026.

A PRE-screen by Claude for the author to check, not the final screening. Two steps:

1. Keyword triage: a record that does not mention both a language-model term and an energy term in its title or
   abstract cannot meet inclusion criterion I3 with I2, and is excluded with that reason.
2. Title screening of the remaining 432 records against the criteria of thesis Section 3.2: I1 2022-2026; I2
   residential or behind-the-meter assets, whole homes or buildings (search B: any energy management system with a
   small or local language model); I3 the language model interprets requirements, generates constraints, tunes
   parameters, schedules loads or controls devices; I4 evaluated. Excluded: forecasting or text analysis only,
   grid-, market- or data-centre-level operation, the energy use of language models themselves, and topics outside
   energy management. Reviews and position papers are excluded as studies but kept as background.

The decisions below were made by reading the titles (and abstracts where a title was unclear); "unsure" goes to a
second look on the abstract or full text. Re-running overwrites the decision and reason columns.

    uv run python prototypes/slr/prescreen.py
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

OUT = Path(__file__).parent / "out"
LM = re.compile(r"language model|\bLLMs?\b|\bSLMs?\b|GPT|agentic|language agent|LLM-", re.I)
EN = re.compile(r"energy|electric|demand response|load|appliance|heat pump|battery|batteries|photovoltaic|\bPV\b|"
                r"HVAC|thermostat|heating|charging|microgrid|smart grid|power system|EV\b", re.I)  # fmt: skip

INCLUDE = {
    "R0046": "agentic decision support for prosumer energy optimisation",
    "R0125": "LLM shapes the controller's reward for grid-interactive buildings",
    "R0137": "multi-agent smart-home energy management",
    "R0138": "HEMA, multi-agent home energy management assistant",
    "R0151": "lightweight LLMs for intent recognition and action invocation in building energy management (LQ3)",
    "R0160": "LLM-enhanced home energy management with preference elicitation",
    "R0161": "LLM rule synthesis for home energy management",
    "R0168": "LLM-guided RL for heat pump control in buildings",
    "R0175": "LLM agents for home energy management (Jonah et al.)",
    "R0180": "LLM-enhanced vehicle-to-home operation",
    "R0187": "LLM-assisted edge intelligence for smart home energy management (LQ3)",
    "R0189": "multi-agent household electricity scheduling under real-time pricing",
    "R0201": "LLM energy management for multi-tenant buildings with guardrails",
    "R0202": "LLM and RL for home energy management",
    "R0213": "user study of an LLM-integrated building energy management system (LQ2)",
    "R0230": "conversational LLM framework for DRL building energy management",
    "R0243": "fine-tuned LLMs as surrogate schedulers for building energy management",
    "R0250": "agentic vs rule-based smart home energy optimisation (LQ2)",
    "R0259": "residential HVAC control from occupant intention with a multimodal LLM",
    "R0262": "knowledge-augmented multi-agent energy assistant for buildings",
    "R0298": "zero-shot LLM agent with MPC for residential scheduling (Raghavan and Giridhar)",
    "R0299": "conversational demand response between aggregator and prosumers (El Makroum et al.)",
    "R0313": "multi-agent LLM building energy management balancing comfort and cost",
    "R0325": "SLM-based agentic energy orchestration (LQ3)",
    "R0336": "LLM agent for real-world air-conditioning optimisation, long-term deployment",
    "R0349": "AgentiControl-MPC: LLM multi-agent system configures MPC for buildings (SQ2)",
    "R0354": "iterative LLM-augmented RL for home energy management",
    "R0376": "smart home platform with energy-aware digital twin and LLM agent",
    "R0386": "small-scale LLM-enhanced DRL for prosumer energy management (LQ3)",
    "R0389": "RLHF pipeline for LLM-based smart building optimisation",
    "R0396": "evaluation framework for conversational home energy management systems (LQ2)",
    "R0488": "LLM for generalisation in building energy management",
    "R0496": "LLM interface for home energy management systems (Michelon et al.)",
    "R0501": "LLM-MAC, multi-agent home energy management",
    "R0503": "LLM-BEM, zero-shot LLM agent scheduling for building energy management",
    "R0504": "LLM battery-health-aware scheduling in buildings",
    "R0524": "hybrid LSTM and LLM recommendations for smart home energy management",
    "R0525": "intent-guided battery scheduling in buildings",
    "R0533": "LLM guidance for energy-efficient appliance use",
    "R0581": "context-aware LLM agents for energy management in smart buildings",
    "R0590": "LLM agent explains building energy management policies",
    "R0593": "1-bit LLM agents for smart home lighting (LQ3)",
    "R0602": "LLM-assisted rule-based control of PV-driven air conditioning",
    "R0607": "validated framework for personalised residential energy management with LLMs",
    "R0610": "agentic AI home energy management system (El Makroum et al.)",
    "R0619": "AI agents with IoT for smart home energy optimisation",
    "R0621": "multi-agent demand response for residential loads (CrewAI)",
    "R0657": "privacy-preserving energy recommendations with local LLMs on the edge (LQ3)",
    "R0662": "multimodal foundation models in the loop of office HVAC control",
    "R0668": "LLM-based interpretable control in building energy systems (Zhang and Chen)",
    "R0674": "LLM-based building energy management assistants",
    "R0684": "GPT prompting to schedule appliances for cost",
    "R0696": "LLM-assisted optimisation autoformalism for energy management (NL to optimisation)",
}  # fmt: skip
UNSURE = {
    "R0006": "occupant-AI interaction in building energy management: check the LLM's role",
    "R0007": "LLM-simulated users to evaluate conversational energy management (method, LQ2)",
    "R0009": "LLM household energy scenario generation: data or control?",
    "R0018": "on-device LLM for smart-home commands (LQ3), no energy objective stated",
    "R0032": "agentic virtual power plants for energy communities: reference architecture, evaluated?",
    "R0033": "smart home energy monitoring architecture: check the LLM's role",
    "R0039": "LLMs as operators for EV charging scheduling: home or station?",
    "R0072": "LLM recommendations in a smart home: energy related?",
    "R0095": "verification of LLM-assisted energy-control software (relevant to the checker)",
    "R0100": "residential HVAC control under changing preferences: LLM used?",
    "R0105": "LLM-MARL lighting control from user intent: energy objective?",
    "R0106": "personalised home energy management with NILM and HITL RL: LLM used?",
    "R0152": "SLM sensor-text grounding on consumer AIoT devices (LQ3): energy related?",
    "R0155": "LLMs for personalised smart home automation: energy related?",
    "R0166": "LLM-assisted EV charging scheduling: home or station?",
    "R0169": "LLM demand response for EV users and aggregators: household side?",
    "R0179": "LLM-mediated demand response in microgrids: household level?",
    "R0196": "LLM knowledge in human-computer demand response",
    "R0203": "edge AI for privacy-preserving smart home automation (LQ3): LLM, energy?",
    "R0214": "energy use of LLM smart-home assistants on low-cost devices (SQ4 background)",
    "R0223": "edge-LLM controller with safety layer for greenhouse climate (LQ3)",
    "R0257": "demand response with safety-filtered MADRL: LLM used?",
    "R0291": "energy profiling in context-aware buildings: LLM role?",
    "R0326": "LLM scheduling of fuel-cell cogeneration systems: building level?",
    "R0338": "LLM air-quality monitoring and appliance control: energy objective?",
    "R0341": "agentic generation of urban building energy services",
    "R0342": "agentic BEMS adoption from operator surveys (background for LQ2)",
    "R0352": "generative AI and LLMs for demand-side management with IoT: review or system?",
    "R0353": "LLM constraint relaxation for thermal comfort evaluation",
    "R0394": "hardware-in-the-loop agentic smart home automation: energy objective?",
    "R0407": "LLM-powered smart home for efficient living: evaluated?",
    "R0433": "LSTM and LLMs for energy management: setting?",
    "R0434": "LLM smart building recommendations: control or text?",
    "R0435": "LLM virtual assistants for smart building operations",
    "R0456": "LLM demand response for EV users and aggregators: household side?",
    "R0460": "residential home energy advisor: LLM role?",
    "R0473": "ontology-driven LLM knowledge graph for smart buildings",
    "R0507": "LLMs for public building energy management: assessment, evaluated?",
    "R0513": "HEMS with transformer and PSO: language model or not?",
    "R0518": "AI and IoT for smart home energy management: LLM used?",
    "R0521": "modular proof of concept of AI in smart buildings: LLM role?",
    "R0532": "LLM chatbot generating Home Assistant automations: energy related?",
    "R0537": "digital twins and LLMs for energy flexibility services: building level?",
    "R0548": "explanations of a solar smart-home recommender: LLM used?",
    "R0554": "digital twin with LLMs for building energy management interoperability",
    "R0574": "AI-enhanced IoT energy management for a rural home: LLM used?",
    "R0599": "AI user interaction with smart homes, case study: energy related?",
    "R0627": "bi-level optimisation of household flexible loads: LLM used?",
    "R0675": "interpretable ML control in building energy systems: same study as R0668?",
    "R0695": "LLM chatbot designing home automation routines: energy related?",
    "R0705": "LLM modelling and optimisation of user-centric EV charging: home?",
    "R0711": "LLM recommendation system for prosumers",
    "R0719": "LLM goal-oriented reasoning in smart homes: energy related?",
}  # fmt: skip
# Small or locally run models that control smart-home devices without an energy objective: outside I2, but evidence
# for LQ3 (can a small model on home hardware act on household requests?)
LQ3_BACKGROUND = {"R0008", "R0017", "R0027", "R0034", "R0172", "R0219", "R0357", "R0390", "R0408", "R0447", "R0464",
                  "R0474", "R0475", "R0561", "R0576", "R0499"}  # fmt: skip
BACKGROUND = {"R0040", "R0163", "R0228", "R0232", "R0314", "R0344", "R0364", "R0374", "R0381", "R0382", "R0451",
              "R0463", "R0638", "R0671", "R0133", "R0071"}  # fmt: skip


# Other versions of a study already in the set, found during screening; moved to identification by the author
# (24 Nov 2026). The journal version is kept.
DUPLICATES = {
    "R0408": "duplicate: arXiv preprint of R0034 (Huang et al., IEEE TMC 2026), journal version kept",
    "R0464": "duplicate: MobiCom 2025 poster of R0034 (Huang et al., IEEE TMC 2026), journal version kept",
}  # fmt: skip


def reason_for_exclusion(title: str) -> str:
    if re.search(r"forecast|prediction|predict", title, re.I):
        return "forecasting or prediction only"
    if re.search(r"inference|serving|accelerat|KV.?cache|mixture-of-experts|\bMoE\b|GPU|training|token|edge LLM|"
                 r"on-device|processor|memory", title, re.I):  # fmt: skip
        return "language-model computing or energy use, not energy management"
    if re.search(r"grid|power system|distribution network|microgrid|virtual power plant|market|trading|data cent|"
                 r"substation|transmission|integrated energy system|hydropower|wind|storage system", title, re.I):  # fmt: skip
        return "grid, market or plant level, no household or building"
    return "outside scope: not a language model in home or building energy management"


def main() -> None:
    path = OUT / "screening.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    for r in rows:
        text = r["title"] + " " + r["abstract"]
        if r["id"] in INCLUDE:
            r["decision"], r["reason"] = "include", INCLUDE[r["id"]]
        elif r["id"] in UNSURE:
            r["decision"], r["reason"] = "unsure", UNSURE[r["id"]]
        elif r["id"] in LQ3_BACKGROUND:  # included by the author's decision, 24 Nov 2026 (was unsure)
            r["decision"], r["reason"] = "include", "LQ3 background: small or local model controls smart-home devices, no energy objective"
        elif r["id"] in BACKGROUND:
            r["decision"], r["reason"] = "exclude", "review or position paper (kept as background)"
        elif r["abstract"] and not (LM.search(text) and EN.search(text)):
            r["decision"], r["reason"] = "exclude", "keyword triage: no language-model and energy terms together"
        else:
            r["decision"], r["reason"] = "exclude", reason_for_exclusion(r["title"])
    # Second look at the unsure records on their abstracts (Claude's proposals, approved by the author on
    # 24 Nov 2026 as a whole): ``out/unsure_proposals.csv`` overrides the decision and reason above.
    proposals = {p["id"]: p for p in csv.DictReader((OUT / "unsure_proposals.csv").open(encoding="utf-8"))}
    for r in rows:
        if r["id"] in proposals:
            r["decision"], r["reason"] = proposals[r["id"]]["proposed"], proposals[r["id"]]["reason"]
        if r["id"] in DUPLICATES:
            r["decision"], r["reason"] = "duplicate", DUPLICATES[r["id"]]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(Counter(r["decision"] for r in rows))
    print(Counter(r["reason"] for r in rows if r["decision"] == "exclude").most_common())
    missing = (set(INCLUDE) | set(UNSURE) | BACKGROUND | LQ3_BACKGROUND) - {r["id"] for r in rows}
    assert not missing, missing


if __name__ == "__main__":
    main()
