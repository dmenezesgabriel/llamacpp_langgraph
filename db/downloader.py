"""
Downloads public dataset files to a local `data/` directory.

Called by db/loader.py before loading into DuckDB, so datasets are fetched
once and reused across runs — no httpfs extension required.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

DATASET_URLS: dict[str, str] = {
    "nyc_taxi.parquet": "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2019-04.parquet",
    "seattle_weather.csv": "https://raw.githubusercontent.com/vega/vega-datasets/main/data/seattle-weather.csv",
    "movies.json": "https://raw.githubusercontent.com/vega/vega-datasets/main/data/movies.json",
    "cars.json": "https://raw.githubusercontent.com/vega/vega-datasets/main/data/cars.json",
}


def ensure_downloaded() -> dict[str, Path]:
    """
    Download any missing dataset files to DATA_DIR.
    Returns a mapping of filename → local Path for all datasets.
    """
    DATA_DIR.mkdir(exist_ok=True)
    paths: dict[str, Path] = {}

    for filename, url in DATASET_URLS.items():
        dest = DATA_DIR / filename
        paths[filename] = dest
        if dest.exists():
            continue
        print(f"   ↓  Downloading {filename} …", end="", flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req) as response, open(dest, "wb") as f:
                f.write(response.read())
            size_mb = dest.stat().st_size / 1_048_576
            print(f" {size_mb:.1f} MB ✓")
        except Exception as exc:  # noqa: BLE001
            print(f" FAILED ({exc})")
            dest.unlink(missing_ok=True)

    return paths
