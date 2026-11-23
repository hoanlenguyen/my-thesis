"""Confirmatory analysis of the registered evaluation (draft, 22 Nov 2026; becomes final with the registration commit).

Reads only the registered outputs: the SQ1 runs of ``run_heldout.py`` (``--runs``) with the keyed held-out plans
(``--plans``), and for H4 the Configurator's held-out weeks (``--configurator``, one or more JSONL files of
``configurator_pilot/configurator.py``). Nothing here is tuned after the run: every choice below is fixed by the
registration commit, and any deviation is reported as such in the thesis.

Fixed choices (thesis Section 3.5, ``config_heldout.json``):

- The small model tested in H1-H3 is ``BEST_SLM`` (the main candidate, named before the run; choosing the best one
  after the run would make the test depend on the data). The other small models are reported descriptively.
- Units: the plan is the cluster; each system's three runs of a plan are averaged before any comparison.
- H1 (non-inferiority, margin 0.10): decision accuracy and constraint recall of ``slm_checks`` (BEST_SLM) against
  ``llm``. For each metric, the paired difference (small - cloud) is resampled over plans (cluster bootstrap,
  ``BOOT`` replicates, seed 2027); its bootstrap standard error gives z = (difference + margin) / SE and a one-sided
  p-value. Recall is the pooled ratio (sum of items found / sum of key items) within each replicate. H1 holds only
  if both metrics pass (intersection-union), so its p-value is the larger of the two. Exact McNemar on the plans'
  majority decisions is reported alongside.
- H2 (requirements met, null rate 0.90): plans whose key says commit and whose key items are all feasible. A plan
  counts as met when BEST_SLM in ``slm_checks`` committed it and the closed loop met the key in at least two of its
  three runs; asking counts as not met, because the requirement is then not scheduled. One-sided exact binomial test
  of H0: rate <= 0.90.
- H3: decision accuracy of ``slm_checks_fallback`` (BEST_SLM) against ``llm``, as in H1 with margin 0.10 (decision
  accuracy only); and the share of plans sent to the fallback (in at least two of three runs) at most 0.20,
  one-sided exact binomial of H0: share >= 0.20. H3 holds if both pass; its p-value is the larger.
- Holm correction over H1, H2, H3 (SQ1), family alpha 0.05.
- H4 (SQ2): per held-out week and house, the adjusted cost of the MPC configured by BEST_SLM against the auto-tuner
  and against the MPC configured by the cloud model; for each, a paired one-sided Wilcoxon signed-rank test of H0:
  the small model's cost exceeds the other's by at least ``H4_MARGIN_EUR`` per week. H4 holds only if both pass
  (intersection-union), so its p-value is the larger. SQ2 has one hypothesis, so no correction.
- H5 (SQ3): descriptive. The 95th percentile of the time per plan of BEST_SLM in ``slm_checks``, per device, against
  ``H5_LIMIT_S``. The year simulation is reported separately.

    uv run python prototypes/heldout/confirm_heldout.py --plans prototypes/heldout/plans_heldout.json \
        --runs prototypes/heldout/out/heldout.jsonl --configurator prototypes/configurator_pilot/out/heldout_*.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

REGISTERED = False  # set to True in the registration commit; until then the output is marked DRAFT
BEST_SLM = "gemma4-e4b"
CLOUD = "gpt-6-luna"
MARGIN = 0.10  # H1, H3 (author's decision, 21 Nov 2026)
H2_P0 = 0.90  # H2 (author's decision, 21 Nov 2026)
H3_MAX_FALLBACK = 0.20
H4_MARGIN_EUR: float | None = 0.20  # per week (author's decision, 22 Nov 2026)
H5_LIMIT_S: float | None = 15 * 60  # p95 per device (author's decision, 22 Nov 2026)
ALPHA = 0.05
BOOT = 10_000
SEED = 2027


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def by_plan(rows: list[dict], setup: str, model: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["setup"] == setup and r["model"] == model:
            out[r["id"]].append(r)
    return out


def noninferiority(small: dict[str, list[dict]], cloud: dict[str, list[dict]], metric: str,
                   rng: np.random.Generator) -> dict:  # fmt: skip
    """Paired cluster bootstrap over plans of (small - cloud) for 'decision' (mean accuracy) or 'recall' (pooled)."""
    ids = sorted(set(small) & set(cloud))
    if metric == "decision":
        a = np.array([np.mean([bool(r.get("decision_ok")) for r in small[i]]) for i in ids])
        b = np.array([np.mean([bool(r.get("decision_ok")) for r in cloud[i]]) for i in ids])
        num_a, den_a, num_b, den_b = a, np.ones_like(a), b, np.ones_like(b)
    else:  # pooled recall: items found / key items, per plan averaged over runs
        num_a = np.array([np.mean([r["tp"] for r in small[i]]) for i in ids])
        den_a = np.array([np.mean([r["tp"] + r["fn"] for r in small[i]]) for i in ids])
        num_b = np.array([np.mean([r["tp"] for r in cloud[i]]) for i in ids])
        den_b = np.array([np.mean([r["tp"] + r["fn"] for r in cloud[i]]) for i in ids])
    if den_a.sum() == 0:
        return {"plans": len(ids), "note": "no key items"}
    diff = num_a.sum() / den_a.sum() - num_b.sum() / den_b.sum()
    idx = rng.integers(0, len(ids), size=(BOOT, len(ids)))
    boot = num_a[idx].sum(1) / np.maximum(den_a[idx].sum(1), 1e-12) - num_b[idx].sum(1) / np.maximum(den_b[idx].sum(1), 1e-12)
    se = float(boot.std(ddof=1))
    z = (diff + MARGIN) / se if se > 0 else float("inf")
    return {"plans": len(ids), "small": round(float(num_a.sum() / den_a.sum()), 3),
            "cloud": round(float(num_b.sum() / den_b.sum()), 3), "difference": round(float(diff), 3),
            "lower_95": round(float(np.quantile(boot, 0.05)), 3), "se": round(se, 4),
            "p": float(stats.norm.sf(z))}  # fmt: skip


def majority(rows: list[dict], test) -> bool:
    return sum(bool(test(r)) for r in rows) * 2 > len(rows)


def holm(pvalues: dict[str, float]) -> dict[str, dict]:
    order = sorted(pvalues, key=pvalues.get)
    out, still = {}, True
    for rank, name in enumerate(order):
        level = ALPHA / (len(order) - rank)
        still = still and pvalues[name] <= level
        out[name] = {"p": round(pvalues[name], 5), "holm_level": round(level, 5), "rejected": still}
    return out


def feasible_commit(plan: dict) -> bool:
    key = plan["key"]
    items = [*key.get("ev", []), *key.get("appliances", [])]
    return key.get("decision") == "commit" and all(it.get("feasible", True) for it in items)


def sq1(plans: dict[str, dict], rows: list[dict]) -> dict:
    rng = np.random.default_rng(SEED)
    small, cloud = by_plan(rows, "slm_checks", BEST_SLM), by_plan(rows, "llm", CLOUD)
    fb = by_plan(rows, "slm_checks_fallback", BEST_SLM)
    h1 = {m: noninferiority(small, cloud, m, rng) for m in ("decision", "recall")}
    ids = sorted(set(small) & set(cloud))
    s_ok = [majority(small[i], lambda r: r.get("decision_ok")) for i in ids]
    c_ok = [majority(cloud[i], lambda r: r.get("decision_ok")) for i in ids]
    b, c = sum(x and not y for x, y in zip(s_ok, c_ok)), sum(y and not x for x, y in zip(s_ok, c_ok))
    h1["mcnemar_exact_p"] = float(stats.binomtest(min(b, c), b + c, 0.5).pvalue) if b + c else 1.0
    h1["mcnemar_discordant"] = {"small_only": b, "cloud_only": c}
    h1["p"] = max(h1["decision"].get("p", 1.0), h1["recall"].get("p", 1.0))
    eligible = [i for i in small if i in plans and feasible_commit(plans[i])]
    met = sum(majority(small[i], lambda r: r["output"].get("commit") and r.get("loop", {}).get("met")) for i in eligible)
    h2 = {"house_days": len(eligible), "met": met, "rate": round(met / len(eligible), 3) if eligible else None,
          "p": float(stats.binomtest(met, len(eligible), H2_P0, alternative="greater").pvalue) if eligible else 1.0}  # fmt: skip
    h3_dec = noninferiority(fb, cloud, "decision", rng)
    sent = sum(majority(fb[i], lambda r: r.get("fallback")) for i in fb)
    h3_share = {"plans": len(fb), "sent": sent, "share": round(sent / len(fb), 3) if fb else None,
                "p": float(stats.binomtest(sent, len(fb), H3_MAX_FALLBACK, alternative="less").pvalue) if fb else 1.0}  # fmt: skip
    h3 = {"decision": h3_dec, "fallback_share": h3_share, "p": max(h3_dec.get("p", 1.0), h3_share["p"])}
    return {"H1": h1, "H2": h2, "H3": h3, "holm": holm({"H1": h1["p"], "H2": h2["p"], "H3": h3["p"]})}


def descriptive(rows: list[dict]) -> list[dict]:
    """Every set-up and model: decision accuracy, pooled precision and recall, closed loop, fallback, time and cost."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["setup"], r["model"])].append(r)
    out = []
    for (setup, model), rs in sorted(groups.items()):
        tp, fp, fn = (sum(r[k] for r in rs) for k in ("tp", "fp", "fn"))
        loops = [r["loop"]["met"] for r in rs if "loop" in r]
        lat = np.array([r["latency_s"] for r in rs])
        out.append({"setup": setup, "model": model, "answers": len(rs),
                    "decision_accuracy": round(np.mean([bool(r.get("decision_ok")) for r in rs]), 3),
                    "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                    "recall": round(tp / (tp + fn), 3) if tp + fn else None,
                    "failed_answers": sum(bool(r.get("failed_answer")) for r in rs),
                    "loop_met": f"{sum(loops)}/{len(loops)}",
                    "fallback_share": round(np.mean([bool(r.get("fallback")) for r in rs]), 3) if setup == "slm_checks_fallback" else None,
                    "latency_mean_s": round(float(lat.mean()), 1), "latency_p95_s": round(float(np.percentile(lat, 95)), 1),
                    "usd": round(sum(r.get("usd") or 0.0 for r in rs), 4)})  # fmt: skip
    return out


def sq2(paths: list[Path]) -> dict:
    """H4: BEST_SLM-configured MPC vs the auto-tuner and vs the cloud-configured MPC, per house and held-out week."""
    pairs = []
    for path in paths:
        weeks: dict[str, dict[str, float]] = defaultdict(dict)
        for r in load(path):
            weeks[r["week"]][r["system"]] = r["adjusted_cost_eur"]
        for week, systems in sorted(weeks.items()):
            if f"agent:{BEST_SLM}" in systems and "auto_tuner" in systems:
                pairs.append((path.stem, week, systems[f"agent:{BEST_SLM}"], systems["auto_tuner"],
                              systems.get(f"agent:{CLOUD}")))  # fmt: skip
    if not pairs:
        return {"note": "no Configurator weeks given"}
    out: dict = {"weeks": len(pairs), "small_total_eur": round(sum(p[2] for p in pairs), 2)}
    tests = {"auto_tuner": [(s, t) for _, _, s, t, _ in pairs],
             "cloud": [(s, c) for _, _, s, _, c in pairs if c is not None]}  # fmt: skip
    for name, xy in tests.items():
        if not xy:
            out[name] = {"note": "no weeks"}
            continue
        d = np.array([s - o for s, o in xy])  # the small model's extra cost, EUR per week
        out[name] = {"weeks": len(d), "mean_extra_cost_eur": round(float(d.mean()), 3),
                     "other_total_eur": round(sum(o for _, o in xy), 2)}  # fmt: skip
        if H4_MARGIN_EUR is not None:
            out[name]["p"] = float(stats.wilcoxon(d - H4_MARGIN_EUR, alternative="less").pvalue)
    ps = [out[n].get("p") for n in tests]
    if H4_MARGIN_EUR is None or None in ps:
        out["note"] = "H4 not tested (margin not fixed or a comparison without weeks)"
    else:
        out["p"] = max(ps)
        out["rejected"] = out["p"] <= ALPHA
    return out


def sq3(rows: list[dict]) -> dict:
    lat = np.array([r["latency_s"] for r in rows if r["setup"] == "slm_checks" and r["model"] == BEST_SLM])
    out = {"answers": len(lat), "p95_s": round(float(np.percentile(lat, 95)), 1) if len(lat) else None,
           "note": "laptop runs; the devices come from the edge-board runs"}  # fmt: skip
    if H5_LIMIT_S is None:
        out["limit"] = "TO FIX at registration"
    elif len(lat):
        out["within_limit"] = bool(np.percentile(lat, 95) <= H5_LIMIT_S)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--configurator", type=Path, nargs="*", default=[])
    parser.add_argument("--out", type=Path, default=None, help="JSON report (default: next to --runs)")
    args = parser.parse_args()
    plans = {p["id"]: p for p in json.loads(args.plans.read_text(encoding="utf-8"))["plans"]}
    rows = [r for r in load(args.runs) if r["plans_file"] == args.plans.name]
    report = {"status": "REGISTERED" if REGISTERED else "DRAFT: not registered, not a confirmatory result",
              "plans_file": args.plans.name, "answers": len(rows),
              "SQ1": sq1(plans, rows), "SQ2": {"H4": sq2(args.configurator)}, "SQ3": {"H5": sq3(rows)},
              "descriptive": descriptive(rows)}  # fmt: skip
    out = args.out or args.runs.with_name(args.runs.stem + "_confirm.json")
    out.write_text(json.dumps(report, indent=1, default=float), encoding="utf-8")
    print(report["status"])
    s1 = report["SQ1"]
    print(f"H1 decision {s1['H1']['decision']}  recall {s1['H1']['recall']}")
    print(f"H2 {s1['H2']}")
    print(f"H3 {s1['H3']['decision']}  fallback {s1['H3']['fallback_share']}")
    print(f"Holm (SQ1): {s1['holm']}")
    print(f"H4 {report['SQ2']['H4']}\nH5 {report['SQ3']['H5']}\n-> {out}")


if __name__ == "__main__":
    main()
