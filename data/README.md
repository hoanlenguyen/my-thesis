# Data

`raw/` is gitignored — datasets are downloaded locally. Committed scenario sets:

| Directory | Scenarios | Prices | Notes |
|---|---|---|---|
| `scenarios/` | A01–F08 (48) | Sahkotin, hourly, 2022-01 – 2026-09 | main benchmark; type E = Dec 2022 crisis |
| `scenarios_15min/` | Q-A01–Q-F08 (48) | Elering, native 15-min, 2025-10-01 – 2026-09-25 | type E = 16 highest-peak days of the period |
| `pilot/` | SYN-* (48) | synthetic | development only, never thesis results |
| `scenarios_v2/` | factorial (96) | Sahkotin hourly, 2022-01 – 2025-09 | exploratory main set: price pattern x load x peak limit |
| `scenarios_q2/` | Q2-* factorial (96) | Elering 15-min, 2025-10 – 2026-09 | held-out set for the second pre-registration |
| `scenarios_uk2015/` | UK-* factorial (48) | ENTSO-E GB hourly, 2014-12-19 – 2015-07-31 | appendix robustness set: REFIT period, UK tariff |

### UK 2015 appendix set

Matches the REFIT recording period and country. ENTSO-E has GB day-ahead prices only from 17 Dec 2014,
in GBP/MWh (`uv run hems prices --source entsoe --area GB --start 2014-12-17 --end 2015-08-01 --out
data/raw/prices_gb_entsoe.csv`); the window has no negative prices, so the set has three price patterns
(stable, volatile, spike) x 2 loads x 4 days x 2 limits. Prices are converted to EUR at the ECB mean
reference rate of 17 Dec 2014 – 31 Jul 2015 (0.73161 GBP per EUR, `--price-scale 1.366848`), and days run
on London time (`--tz Europe/London`). Tariff `Tariff.uk_2015()`: one constant adder of 10.62 p/kWh
(0.1452 EUR/kWh) for all non-wholesale costs plus 5 % VAT, so that the mean consumer price equals DECC's
2015 average of 15.4 p/kWh (GBP 584 for 3,800 kWh incl. VAT). Built with
`uv run hems build-factorial --prices data/raw/prices_gb_entsoe.csv --out data/scenarios_uk2015 --per-cell 4
--seed 2030 --id-prefix UK- --tz Europe/London --price-scale 1.366848 --tariff uk2015 --allow-fewer`.
UK households had essentially no dynamic hourly tariffs then; the set is a hypothetical check that the
results transfer to the data's own place and time, not a confirmatory test.

Each set has a `manifest.json` recording seed, houses, price source/period/resolution and chosen days.

## REFIT (appliance profiles)

Cleaned REFIT Electrical Load Measurements, Murray et al. (2017), doi:10.1038/sdata.2016.122.

Dataset DOI 10.15129/9ab14b0e-19ac-4279-938f-27f643078cec (Strathclyde Pure, CC BY 4.0).

1. From https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/ download
   `CLEAN_REFIT_081116.7z`, `CLEAN_READ_ME_081116.txt` and `MetaData_Tables.xlsx` into `data/raw/`.
2. Extract the house CSVs into `data/raw/refit/` (6.9 GB for all 20 houses; no 7-Zip needed):
   `uvx --from py7zr python -c "import py7zr; py7zr.SevenZipFile('data/raw/CLEAN_REFIT_081116.7z').extractall('data/raw/refit')"`
3. `uv run hems refit-inspect --refit data/raw/refit` — cycle statistics per mapped column.
   The mapping (`HOUSE_APPLIANCES` in `src/hems/data/refit.py`) is transcribed from the README's
   appliance list. Washer-dryers (houses 1, 8, 9, 18) are not used as profiles; house 12 has no
   washing machine, dishwasher or tumble dryer, and house 19's washing machine never shows a heating
   phase — both are excluded (`EXCLUDED_HOUSES`, reasons recorded in `manifest.json`).

## Nord Pool FI prices

```bash
# Elering (Estonian TSO) public API, no token: native 15-min from 1 Oct 2025, hourly before
uv run hems prices --source elering --start 2022-01-01 --end 2026-09-26 --out data/raw/prices_fi_elering.csv
# official source, native 15-min from 1 Oct 2025 (needs ENTSOE_API_KEY in .env)
uv run hems prices --source entsoe --start 2022-01-01 --end 2026-09-26 --out data/raw/prices_fi_entsoe.csv
# no-token alternative for development: same values, hourly only
uv run hems prices --source sahkotin --out data/raw/prices_fi_sahkotin.csv
```

ENTSO-E token: register at https://transparency.entsoe.eu, then e-mail transparency@entsoe.eu with
subject "Restful API access" and your account e-mail; the token appears under My Account Settings.
Both outputs are spot EUR/MWh excl. VAT with UTC timestamps (the `hems build` defaults).
Any other CSV with a timestamp and a price column also works. Hourly data is repeated ×4.

**Verified against ENTSO-E (6 Oct 2026, `prices_fi_entsoe.csv`, 2022-01-01 to 2026-09-25):** Elering is
identical at all 67,411 timestamps. Sähkötin is identical for every hour before 1 Oct 2025 except one hour
on the DST change day 2023-10-29 (dropped by `to_daily_slots`, in no benchmark); from 1 Oct 2025 it gives
the hourly mean of the official 15-min prices. Every spot price stored in `scenarios_15min/`,
`scenarios_v2/` and `scenarios_q2/` equals ENTSO-E on its day; `scenarios/` (first benchmark) also has
days after Oct 2025, which are hourly by design.

```bash
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi.csv \
  --price-unit EUR/MWh --price-tz UTC --price-vat 0   # adjust to the file's format
```

15-minute benchmark (only days since the 15-min market switch; spike days instead of the 2022 crisis):

```bash
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi_elering.csv   --out data/scenarios_15min --from 2025-10-01 --spike-days top --id-prefix Q-
```

`--price-vat 0.255` if the export already includes VAT; `--price-time-col/--price-col` if column
auto-detection picks the wrong ones. The build fails loudly if any scenario type lacks candidate days.
