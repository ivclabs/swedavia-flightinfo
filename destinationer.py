"""Count where flights come from or go to, and attach a country offline.

city_country.json is loaded once. Filtering by country uses that table, so a
filter such as "Spain" does not call another API.
"""

from __future__ import annotations

import json
from pathlib import Path

from airport import _load_dotenv, choose_airport, choose_date, fetch_day, norm

_DATA = json.loads(Path(__file__).with_name("city_country.json").read_text(encoding="utf-8"))
CITY_TO_COUNTRY: dict[str, str] = {norm(city): country for city, country in _DATA["city_to_country"].items()}
COUNTRY_TO_CITIES: dict[str, list[str]] = {}
for _city, _country in CITY_TO_COUNTRY.items():
    COUNTRY_TO_CITIES.setdefault(_country.lower(), []).append(_city)


def lookup_country(city_name: str) -> str:
    """Case-insensitive country lookup. 'Frankfurt am Main' still finds Frankfurt."""
    key = norm(city_name)
    if not key:
        return ""
    exact = CITY_TO_COUNTRY.get(key)
    if exact:
        return exact
    best_country = ""
    best_length = 10**9
    for candidate, country in CITY_TO_COUNTRY.items():
        if not _prefix_match(key, candidate):
            continue
        # The shortest city name that fits is the general one: "paris", not a longer variant.
        if len(candidate) < best_length:
            best_country = country
            best_length = len(candidate)
    return best_country


def _prefix_match(left: str, right: str) -> bool:
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    if len(short) < 4 or not long.startswith(short):
        return False
    return len(long) == len(short) or long[len(short)] in " -/"


def filter_rows(counts: dict[str, int], query: str) -> list[tuple[str, int, str]]:
    query_key = norm(query)
    matched_cities: set[str] = set()
    if query_key:
        for country, cities in COUNTRY_TO_CITIES.items():
            country_key = norm(country)
            if country_key == query_key or country_key.startswith(query_key):
                matched_cities.update(cities)
    rows: list[tuple[str, int, str]] = []
    for city, count in counts.items():
        country = lookup_country(city)
        if not query_key:
            rows.append((city, count, country))
            continue
        city_key = norm(city)
        if query_key in city_key or query_key in norm(country) or city_key in matched_cities:
            rows.append((city, count, country))
    rows.sort(key=lambda row: (-row[1], row[0].lower()))
    return rows


def _city_of(flight: dict, kind: str) -> str:
    if kind == "arrivals":
        return flight.get("departureAirportEnglish") or "Okänd"
    return flight.get("arrivalAirportEnglish") or "Okänd"


def main() -> None:
    _load_dotenv()
    print("Destinationsöversikt — Swedavia FlightInfo API v2")
    print("Räknar städer och slår upp landet lokalt från city_country.json.")
    try:
        while True:
            kind = input("\nAnkomster eller avgångar? (a/d, q avslutar): ").strip().lower()
            if kind in {"q", "quit"}:
                print("Avslutar.")
                return
            if kind not in {"a", "d", "arrivals", "departures"}:
                print("Skriv a eller d.")
                continue
            endpoint = "arrivals" if kind.startswith("a") else "departures"
            airport = choose_airport()
            if airport is None:
                continue
            date = choose_date()
            if date is None:
                continue
            flights = fetch_day(endpoint, airport, date)
            counts: dict[str, int] = {}
            for flight in flights:
                city = _city_of(flight, endpoint)
                counts[city] = counts.get(city, 0) + 1
            query = input("Filtrera på land eller stad (tomt = alla): ").strip()
            rows = filter_rows(counts, query)
            if not rows:
                print("Inga destinationer matchade.")
                continue
            width = max(len(city) for city, _count, _country in rows)
            total = sum(count for _city, count, _country in rows)
            print(f"\n{len(rows)} städer, {total} flyg")
            for city, count, country in rows:
                print(f"{city:<{width}}  ({count:3} st) [{country or '?'}]")
    except (KeyboardInterrupt, EOFError):
        print("\nAvslutar.")


if __name__ == "__main__":
    main()
