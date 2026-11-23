"""Power calculation for the size of the held-out plan set (draft for the registration, 21 Nov 2026).

Inputs from the exploratory ReAct pilot (``react_gateway/out/results.jsonl``, plans.json + plans_dev.json, 36 plans):
Gemma 4 E4B and GPT-6 Luna disagreed on 4 of 36 decisions (discordance 0.11), and a plan had 1.1 constraint items
on average. Each figure is the power of the registered test at the first (strictest) Holm step of SQ1, which has three
hypotheses (H1, H2, H3): one-sided alpha 0.05 / 3.

- H1/H3, decision accuracy, non-inferiority margin 0.05: paired difference small model - cloud LLM, lower bound of the
  one-sided interval above -0.05. Simulated: each plan is concordant, or discordant in favour of either model.
- H1, constraint recall: the same on items, treating items as independent (the cluster bootstrap over plans is a
  little wider; plans have about one item, so the difference is small).
- H2, requirements met on feasible committed house-days: one-sided exact binomial test of p0 = 0.95.

    uv run python prototypes/heldout/power.py
"""

from __future__ import annotations

import numpy as np
from scipy import stats

ALPHA = 0.05 / 3  # first Holm step of SQ1 (H1, H2, H3)
MARGIN = 0.05
SIMS = 20_000
rng = np.random.default_rng(2027)


def paired_noninferiority_power(n: int, discordance: float, true_diff: float, margin: float = MARGIN) -> float:
    """Power of 'lower bound of the paired difference > -MARGIN' (normal approximation of the bootstrap)."""
    p_plus, p_minus = discordance / 2 + true_diff / 2, discordance / 2 - true_diff / 2
    if p_minus < 0:
        return float("nan")
    counts = rng.multinomial(n, [p_plus, p_minus, 1 - discordance], size=SIMS)
    diff = (counts[:, 0] - counts[:, 1]) / n
    var = (counts[:, 0] + counts[:, 1]) / n - diff**2
    se = np.sqrt(np.maximum(var, 1e-12) / n)
    return float(np.mean(diff - stats.norm.ppf(1 - ALPHA) * se > -margin))


def n_for_power(discordance: float, margin: float, power: float = 0.8) -> int:
    """Plans (or items) for the given power at true difference 0 (normal approximation)."""
    z = stats.norm.ppf(1 - ALPHA) + stats.norm.ppf(power)
    return int(np.ceil(z**2 * discordance / margin**2))


def binomial_power(n: int, p_true: float, p0: float = 0.95) -> float:
    """Power of the one-sided exact binomial test H0: p <= p0."""
    k_crit = int(stats.binom.isf(ALPHA, n, p0)) + 1  # smallest k with P(X >= k | p0) <= ALPHA
    while stats.binom.sf(k_crit - 1, n, p0) > ALPHA:
        k_crit += 1
    return float(stats.binom.sf(k_crit - 1, n, p_true))


def main() -> None:
    print(f"one-sided alpha {ALPHA:.4f} (0.05 / 3, first Holm step of SQ1), margin {MARGIN}\n")
    print("H1/H3 decision accuracy, non-inferiority (power for n plans)")
    sizes = (60, 80, 100, 120, 150, 200)
    print("discordance  true diff  " + "  ".join(f"n={n:<4d}" for n in sizes))
    for disc in (0.05, 0.11, 0.15):
        for diff in (0.0, -0.02):
            row = [paired_noninferiority_power(n, disc, diff) for n in sizes]
            print(f"{disc:11.2f}  {diff:9.2f}  " + "  ".join(f"{p:6.2f}" for p in row))
    print("\nThe same with margin 0.10")
    print("discordance  true diff  " + "  ".join(f"n={n:<4d}" for n in sizes))
    for disc in (0.05, 0.11, 0.15):
        for diff in (0.0, -0.02):
            row = [paired_noninferiority_power(n, disc, diff, 0.10) for n in sizes]
            print(f"{disc:11.2f}  {diff:9.2f}  " + "  ".join(f"{p:6.2f}" for p in row))
    print("\nPlans (or items) for power 0.8 at true difference 0")
    for disc in (0.05, 0.11, 0.15, 0.20):
        print(f"  discordance {disc:.2f}: margin 0.05 -> {n_for_power(disc, 0.05)}, "
              f"margin 0.10 -> {n_for_power(disc, 0.10)}")
    print("\nH1 constraint recall, non-inferiority (power for n items; about 1.1 items per pilot plan)")
    sizes = (100, 150, 200, 250, 300)
    print("discordance  true diff  " + "  ".join(f"n={n:<4d}" for n in sizes))
    for disc in (0.10, 0.15, 0.20):
        row = [paired_noninferiority_power(n, disc, 0.0) for n in sizes]
        print(f"{disc:11.2f}  {0.0:9.2f}  " + "  ".join(f"{p:6.2f}" for p in row))
    print("\nH2 requirements met, exact binomial vs 0.95 (power for n feasible committed house-days)")
    sizes = (40, 60, 80, 100, 150)
    print("true rate  " + "  ".join(f"n={n:<4d}" for n in sizes))
    for p in (0.97, 0.98, 0.99, 1.00):
        print(f"{p:9.2f}  " + "  ".join(f"{binomial_power(n, p):6.2f}" for n in sizes))
    print("\nH2 needs at least this many feasible committed house-days for power 0.8:")
    for p in (0.98, 0.99, 1.00):
        n = next(n for n in range(10, 1000) if binomial_power(n, p) >= 0.8)
        print(f"  true rate {p:.2f}: {n}")


if __name__ == "__main__":
    main()
