"""Rebuild city_country.json from the public OurAirports data set.

The reference program used a Swedavia statistics sheet of about 263 cities.
This table is wider on purpose: it covers scheduled-service airports, so an
English name returned by FlightInfo still resolves to a country offline.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from pathlib import Path
from urllib.request import urlopen

AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
COUNTRIES_URL = "https://davidmegginson.github.io/ourairports-data/countries.csv"
OUT = Path(__file__).with_name("city_country.json")

# Names that show up in flight feeds and are easy to miss in the raw columns.
EXTRAS = {
    "annecy/meythet": "France",
    "hyere-le palvestre": "France",
    "aalen-elchingen": "Germany",
    "deauville": "France",
    "orleans": "France",
    "gander": "Canada",
    "rovaniemi": "Finland",
    "billund": "Denmark",
    "krakow": "Poland",
    "london lhr": "United Kingdom",
    "london heathrow": "United Kingdom",
    "new york newark": "United States",
    "newark": "United States",
    "gdansk": "Poland",
}


def norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    folded = folded.replace("&", " and ")
    folded = re.sub(r"[^a-z0-9/+ -]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def download(url: str) -> str:
    with urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def build() -> dict[str, str]:
    countries = {row["code"]: row["name"] for row in csv.DictReader(io.StringIO(download(COUNTRIES_URL)))}
    rank = {"large_airport": 3, "medium_airport": 2, "small_airport": 1}
    best: dict[str, tuple[int, str]] = {}

    def put(raw: str, score: int, country: str) -> None:
        key = norm(raw)
        if len(key) < 3 or not country:
            return
        current = best.get(key)
        if current is None or score > current[0]:
            best[key] = (score, country)

    for row in csv.DictReader(io.StringIO(download(AIRPORTS_URL))):
        if row.get("scheduled_service") != "yes" or row.get("type") not in rank:
            continue
        country = countries.get(row.get("iso_country") or "")
        if not country:
            continue
        score = rank[row["type"]]
        municipality = (row.get("municipality") or "").strip()
        name = (row.get("name") or "").strip()
        if municipality:
            put(municipality, score, country)
            short = re.split(r"[,(]", municipality, maxsplit=1)[0]
            put(short, score, country)
            first = short.split()[0] if short.split() else ""
            if score == 3 and len(norm(first)) >= 4:
                put(first, score, country)
        cleaned = name
        for suffix in (" International Airport", " Airport", " Airfield", " Air Base"):
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]
                break
        if cleaned:
            put(cleaned, score, country)

    for key, country in EXTRAS.items():
        put(key, 9, country)
    return {key: country for key, (_score, country) in sorted(best.items())}


def main() -> None:
    mapping = build()
    OUT.write_text(
        json.dumps({"city_to_country": mapping}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(mapping)} cities to {OUT.name}")


if __name__ == "__main__":
    main()
