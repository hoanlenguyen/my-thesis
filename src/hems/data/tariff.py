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

    @classmethod
    def uk_2015(cls) -> Tariff:
        """Hypothetical UK spot-price tariff for the REFIT period (appendix robustness set, Dec 2014 to Jul 2015).

        DECC's average UK standard electricity bill in 2015 was GBP 584 for 3,800 kWh including 5 % VAT
        (Domestic energy bills in 2015, Energy Trends March 2016), i.e. 15.4 p/kWh, or 14.67 p/kWh before VAT.
        The mean GB day-ahead price over the 224 complete days of 18 Dec 2014 to 31 Jul 2015 (ENTSO-E) was
        40.47 GBP/MWh = 4.05 p/kWh, so all non-wholesale costs (network, policy, supplier, standing charge
        spread over consumption) are one constant adder of 10.62 p/kWh. Converted at the ECB mean rate of the
        window, 0.73161 GBP per EUR: 0.1452 EUR/kWh. Stored in the transfer field; margin and tax are zero.
        """
        return cls(vat=0.05, retail_margin_eur_per_kwh=0.0, transfer_eur_per_kwh=0.1452, electricity_tax_eur_per_kwh=0.0)

    def consumer_price(self, spot_eur_per_kwh: np.ndarray | list[float]) -> np.ndarray:
        spot = np.asarray(spot_eur_per_kwh, dtype=float)
        return (spot + self.retail_margin_eur_per_kwh + self.transfer_eur_per_kwh + self.electricity_tax_eur_per_kwh) * (
            1 + self.vat
        )
