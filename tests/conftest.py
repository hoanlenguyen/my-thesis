from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from hems.core.models import Scenario
from hems.data.scenarios import compose_scenario
from hems.data.synthetic import FIXED, PROFILE_POOL, synthetic_base_load, synthetic_spot


def make_scenario(scenario_type: str = "B", seed: int = 1) -> Scenario:
    rng = np.random.default_rng(seed)
    return compose_scenario(
        scenario_id=f"TEST-{scenario_type}{seed}",
        scenario_type=scenario_type,  # type: ignore[arg-type]
        day=date(2026, 1, 15),
        spot_eur_per_kwh=synthetic_spot(scenario_type, rng),
        base_load_kw=synthetic_base_load(rng),
        profile_pool=PROFILE_POOL,
        fixed_appliances=FIXED,
        rng=rng,
        synthetic=True,
    )


@pytest.fixture
def scenario() -> Scenario:
    return make_scenario("B", seed=3)
