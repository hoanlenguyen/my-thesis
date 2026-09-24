"""Consumer electricity price from the Nord Pool FI spot price.

Scheduling cost uses the consumer price rather than raw spot so that costs stay
positive on negative-price days (Type F), which keeps the optimality gap
(agent - MILP) / MILP well defined. The default component values are typical
Finnish 2025-26 figures; set them to the values cited in the thesis.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Tariff:
    vat: float = 0.255  # Finnish VAT since Sept 2024
    retail_margin_eur_per_kwh: float = 0.005  # typical spot-contract margin
    transfer_eur_per_kwh: float = 0.05  # distribution (transfer) fee, varies by DSO
    electricity_tax_eur_per_kwh: float = 0.02253  # tax class I, excl. VAT

    def consumer_price(self, spot_eur_per_kwh: np.ndarray | list[float]) -> np.ndarray:
        spot = np.asarray(spot_eur_per_kwh, dtype=float)
        return (spot + self.retail_margin_eur_per_kwh + self.transfer_eur_per_kwh + self.electricity_tax_eur_per_kwh) * (
            1 + self.vat
        )
