# Data

`raw/` is gitignored — datasets are downloaded locally. `scenarios/` (the frozen 48-scenario
benchmark + `manifest.json`) and `pilot/` (synthetic dev scenarios) are committed.

## REFIT (appliance profiles)

Cleaned REFIT Electrical Load Measurements, Murray et al. (2017), doi:10.1038/sdata.2016.122.

1. Download the cleaned CSVs (https://zenodo.org/records/5063428) for houses 1–3.
2. Put `CLEAN_House1.csv`, `CLEAN_House2.csv`, `CLEAN_House3.csv` in `data/raw/refit/`.
3. Check the appliance-column mapping in `src/hems/data/refit.py` against the README in the download,
   then run `uv run hems refit-inspect --refit data/raw/refit` — each mapped column should show
   plausible cycle counts, durations (dishwasher/washer ~1–3 h, dryer ~1–2 h) and peak power.

## Nord Pool FI prices

Any CSV with one timestamp column and one price column, covering at least Dec 2022 (Type E),
winters (Type D) and negative-price summer days (Type F). Hourly data is repeated ×4.

```bash
uv run hems build --refit data/raw/refit --prices data/raw/prices_fi.csv \
  --price-unit EUR/MWh --price-tz UTC --price-vat 0   # adjust to the file's format
```

`--price-vat 0.255` if the export already includes VAT; `--price-time-col/--price-col` if column
auto-detection picks the wrong ones. The build fails loudly if any scenario type lacks candidate days.
