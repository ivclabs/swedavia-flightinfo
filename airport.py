"""Terminal client for the Swedavia FlightInfo API v2.

The menu matches the reference program: arrivals, departures, a flight-number
search, an OData query, a heartbeat check, and a short demo of every endpoint.
The subscription key is read from the environment. It is never stored here.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://api.swedavia.se/flightinfo/v2"
PAGE_SIZE = 50
_SE_TZ = ZoneInfo("Europe/Stockholm")
_LAST_QUERY = 0.0

AIRPORTS = {
    "ARN": "Stockholm Arlanda",
    "GOT": "Göteborg Landvetter",
    "BMA": "Stockholm Bromma",
    "MMX": "Malmö",
    "LLA": "Luleå",
    "UME": "Umeå",
    "OSD": "Östersund",
    "VBY": "Visby",
    "RNB": "Ronneby",
    "KRN": "Kiruna",
}

# City names and common spellings. Checked after the IATA code.
_AIRPORT_ALIASES = {
    "arlanda": "ARN",
    "stockholm": "ARN",
    "stockholm arlanda": "ARN",
    "landvetter": "GOT",
    "goteborg": "GOT",
    "goteborg landvetter": "GOT",
    "gothenburg": "GOT",
    "bromma": "BMA",
    "stockholm bromma": "BMA",
    "malmo": "MMX",
    "sturup": "MMX",
    "lulea": "LLA",
    "umea": "UME",
    "ostersund": "OSD",
    "visby": "VBY",
    "gotland": "VBY",
    "ronneby": "RNB",
    "kallinge": "RNB",
    "kiruna": "KRN",
}


def norm(text: str) -> str:
    """Lowercase and drop accents so 'Malmö' and 'malmo' match."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    folded = folded.lower().replace("&", " and ")
    folded = re.sub(r"[^a-z0-9/+ -]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _load_dotenv() -> None:
    path = Path(__file__).with_name(".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _headers() -> dict[str, str]:
    return {
        "Ocp-Apim-Subscription-Key": os.environ.get("SWEDAVIA_API_KEY", ""),
        "Accept": "application/json",
    }


def _fmt_time(utc_str: str | None) -> str:
    """Convert '2026-02-25T16:25:00Z' to '16:25 UTC → 17:25 CET'."""
    if not utc_str or utc_str == "N/A":
        return "-"
    try:
        dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    except ValueError:
        return utc_str
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
    dt_se = dt_utc.astimezone(_SE_TZ)
    return f"{dt_utc.strftime('%H:%M')} UTC → {dt_se.strftime('%H:%M')} {dt_se.strftime('%Z')}"


def _is_valid_flight(flight: dict) -> bool:
    """Return False for ghost rows where every useful field is empty."""
    has_id = bool(flight.get("flightId"))
    has_place = bool(flight.get("departureAirportEnglish") or flight.get("arrivalAirportEnglish"))
    times = flight.get("arrivalTime") or flight.get("departureTime") or {}
    has_time = bool(isinstance(times, dict) and times.get("scheduledUtc"))
    return has_id or has_place or has_time


def _is_upcoming(flight: dict) -> bool:
    """A flight is still upcoming when the API has no actual departure/arrival time."""
    times = flight.get("arrivalTime") or flight.get("departureTime") or {}
    if not isinstance(times, dict) or not times.get("scheduledUtc"):
        return False
    return not times.get("actualUtc")


def _unwrap_flights(item: dict) -> list[dict]:
    """Arrivals and departures return a flight. Query wraps it in arrival/departure."""
    if item.get("flightId") or item.get("arrivalTime") or item.get("departureTime"):
        return [item]
    found: list[dict] = []
    for side in ("arrival", "departure"):
        value = item.get(side)
        if isinstance(value, dict) and (value.get("flightId") or value.get("arrivalTime") or value.get("departureTime")):
            found.append(value)
    return found


def _respect_query_limit() -> None:
    """The query endpoint rejects more than one call every two seconds."""
    global _LAST_QUERY
    if not _LAST_QUERY:
        return
    wait = 2.1 - (time.monotonic() - _LAST_QUERY)
    if wait > 0:
        print(f"  väntar {wait:.1f}s (query-gräns: 1 anrop / 2 s)")
        time.sleep(wait)


def _get(url: str, params: dict | None = None) -> dict | None:
    """GET one URL and return a JSON object, or None when the call failed."""
    print(f"\n→ GET {url}")
    if params:
        print(f"  params: {params}")
    if not os.environ.get("SWEDAVIA_API_KEY"):
        print("  Saknar API-nyckel. Sätt SWEDAVIA_API_KEY eller lägg den i .env.")
        print("  Egen nyckel: https://apideveloper.swedavia.se/")
        return None
    if url.rstrip("/").endswith("/query"):
        _respect_query_limit()
    try:
        response = requests.get(url, headers=_headers(), params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"  Nätverksfel: {exc}")
        return None
    finally:
        if url.rstrip("/").endswith("/query"):
            global _LAST_QUERY
            _LAST_QUERY = time.monotonic()
    print(f"  status: {response.status_code}")
    if response.status_code == 429:
        print("  För många anrop. Vänta två sekunder och försök igen.")
        return None
    if response.status_code in {401, 403}:
        print("  Nyckeln accepterades inte. Kontrollera SWEDAVIA_API_KEY.")
        return None
    if response.status_code == 204 or not response.content:
        return {}
    if response.status_code >= 400:
        print(f"  Fel från API: {response.text[:300]}")
        return None
    try:
        data = response.json()
    except ValueError:
        return {"_raw": response.text.strip()}
    if isinstance(data, dict):
        return data
    return {"_raw": data}


def _collect_flights(url: str, params: dict | None, *, follow_token: bool) -> list[dict]:
    """Follow continuationtoken when the API pages the result."""
    flights: list[dict] = []
    seen: set[str] = set()
    token: str | None = None
    for _page in range(12):
        call = dict(params or {})
        if token:
            call["continuationtoken"] = token
        data = _get(url, call or None)
        if not data:
            break
        batch = data.get("flights") or []
        if not isinstance(batch, list):
            break
        for item in batch:
            if isinstance(item, dict):
                flights.extend(flight for flight in _unwrap_flights(item) if _is_valid_flight(flight))
        if not follow_token:
            break
        new_token = data.get("continuationtoken") or data.get("continuationToken")
        if not new_token or str(new_token) in seen or not batch:
            break
        seen.add(str(new_token))
        token = str(new_token)
    return flights


def fetch_day(kind: str, airport: str, date: str) -> list[dict]:
    """kind is 'arrivals' or 'departures'. date is YYYY-MM-DD."""
    return _collect_flights(f"{BASE_URL}/{airport}/{kind}/{date}", None, follow_token=True)


def fetch_query(filter_expr: str, count: int = 50) -> list[dict]:
    """OData filter. scheduled dates use YYMMDD, for example 260224."""
    params: dict[str, Any] = {"count": max(1, min(count, 1000))}
    if filter_expr:
        params["filter"] = filter_expr
    return _collect_flights(f"{BASE_URL}/query", params, follow_token=True)


def to_odata_date(iso_date: str) -> str:
    year, month, day = iso_date.split("-")
    return f"{year[2:]}{month}{day}"


def resolve_airport(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    upper = text.upper()
    if upper in AIRPORTS:
        return upper
    key = norm(text)
    if key in _AIRPORT_ALIASES:
        return _AIRPORT_ALIASES[key]
    hits = [code for code, name in AIRPORTS.items() if key and key in norm(name)]
    if len(hits) == 1:
        return hits[0]
    return None


def parse_date(raw: str) -> str | None:
    text = raw.strip().lower()
    today = datetime.now(_SE_TZ).date()
    words = {
        "nu": today,
        "idag": today,
        "today": today,
        "imorgon": today + timedelta(days=1),
        "i morgon": today + timedelta(days=1),
        "tomorrow": today + timedelta(days=1),
        "igar": today - timedelta(days=1),
        "igår": today - timedelta(days=1),
        "yesterday": today - timedelta(days=1),
    }
    if text in words:
        return words[text].isoformat()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _print_flight(flight: dict, index: int | None = None, home_airport: str | None = None) -> None:
    prefix = f"[{index}] → " if index is not None else ""
    airline = flight.get("airlineOperator") or {}
    if not isinstance(airline, dict):
        airline = {}
    times = flight.get("arrivalTime") or flight.get("departureTime") or {}
    if not isinstance(times, dict):
        times = {}
    loc = flight.get("locationAndStatus") or {}
    if not isinstance(loc, dict):
        loc = {}
    baggage = flight.get("baggage") or {}
    if not isinstance(baggage, dict):
        baggage = {}
    via = [
        item.get("airportEnglish", "")
        for item in flight.get("viaDestinations") or []
        if isinstance(item, dict) and item.get("airportEnglish")
    ]
    remarks = [
        item.get("text", "")
        for item in flight.get("remarksEnglish") or []
        if isinstance(item, dict) and item.get("text")
    ]
    # The airport you asked for is not repeated inside each flight.
    origin = flight.get("departureAirportEnglish") or (f"({home_airport})" if home_airport else "N/A")
    destination = flight.get("arrivalAirportEnglish") or (f"({home_airport})" if home_airport else "N/A")
    gate = loc.get("gate") or "N/A"
    terminal = loc.get("terminal") or "N/A"
    status = loc.get("flightLegStatusEnglish") or loc.get("flightLegStatus") or "N/A"
    bag = baggage.get("baggageClaimUnit") or "N/A"

    print("—" * 55)
    print(f"{prefix}{flight.get('flightId') or 'N/A'} | {airline.get('name') or 'N/A'} ({airline.get('iata') or ''})")
    print(f"  From    : {origin}")
    print(f"  To      : {destination}")
    print(f"  Status  : {status}")
    print(f"  Terminal: {terminal}  Gate: {gate}")
    print(f"  Baggage : {bag}")
    print(f"  Sched   : {_fmt_time(times.get('scheduledUtc'))}")
    print(f"  Est     : {_fmt_time(times.get('estimatedUtc'))}")
    print(f"  Actual  : {_fmt_time(times.get('actualUtc'))}")
    print(f"  D/I     : {flight.get('diIndicator') or 'N/A'}")
    if via:
        print(f"  Via     : {', '.join(via)}")
    if remarks:
        print(f"  Remarks : {' | '.join(remarks)}")


def _print_flights_paged(flights: list[dict], home_airport: str | None = None) -> None:
    """Print PAGE_SIZE flights at a time. Enter continues, a shows the rest, q stops."""
    total = len(flights)
    if total == 0:
        print("Inga flyg att visa.")
        return
    upcoming = sum(1 for flight in flights if _is_upcoming(flight))
    print(f"\nHämtade {total} flyg ({upcoming} kommande, {total - upcoming} redan avgått eller landat).")
    start = 0
    while start < total:
        page = flights[start : start + PAGE_SIZE]
        for offset, flight in enumerate(page, start + 1):
            _print_flight(flight, offset, home_airport)
        shown = start + len(page)
        remaining = total - shown
        print(f"\n— Visar {shown}/{total} — ({remaining} kvar)")
        if remaining == 0:
            return
        nav = input("[Enter] nästa sida | [a] visa alla | [q] tillbaka till menyn: ").strip().lower()
        if nav == "q":
            print(f"Avbröt efter {shown} flights.")
            return
        if nav == "a":
            for offset, flight in enumerate(flights[shown:], shown + 1):
                _print_flight(flight, offset, home_airport)
            print(f"\n— Visar {total}/{total} — (0 kvar)")
            return
        start = shown


def choose_airport() -> str | None:
    print("\nTillgängliga flygplatser:")
    for code, name in AIRPORTS.items():
        print(f"  {code} – {name}")
    while True:
        raw = input("Ange IATA-kod eller stadsnamn (t.ex. ARN eller Visby): ").strip()
        if raw.lower() in {"q", "quit", "avbryt"}:
            return None
        code = resolve_airport(raw)
        if code:
            return code
        print("⚠ Okänd flygplats, försök igen")


def choose_date() -> str | None:
    while True:
        raw = input("Ange datum (YYYY-MM-DD / nu / idag / imorgon / igår): ").strip()
        if raw.lower() in {"q", "quit", "avbryt"}:
            return None
        parsed = parse_date(raw)
        if parsed:
            return parsed
        print("⚠ Ogiltigt datum. Använd YYYY-MM-DD, idag, imorgon eller igår.")


def show_day(kind: str) -> None:
    airport = choose_airport()
    if airport is None:
        return
    date = choose_date()
    if date is None:
        return
    _print_flights_paged(fetch_day(kind, airport, date), airport)


def search_flight() -> None:
    raw_id = input("Flightnummer (t.ex. SK532): ").strip().upper()
    flight_id = re.sub(r"[^A-Z0-9]", "", raw_id)
    if not flight_id:
        print("Inget flightnummer angavs.")
        return
    airport = choose_airport()
    if airport is None:
        return
    date = choose_date()
    if date is None:
        return
    scheduled = to_odata_date(date)
    filt = f"airport eq '{airport}' and scheduled eq '{scheduled}' and flightId eq '{flight_id}'"
    print(f"Filter: {filt}")
    _print_flights_paged(fetch_query(filt, count=20), airport)


def ask_query() -> None:
    print("\nOData-filter. Tomt filter hämtar en sida flyg från alla flygplatser.")
    print("Exempel: airport eq 'ARN' and scheduled eq '260224' and flightType eq 'D'")
    print("scheduled skrivs YYMMDD. flightType är A (ankomst) eller D (avgång).")
    filt = input("Filter: ").strip()
    if not filt:
        confirm = input("Tomt filter kan bli stort. Fortsätt med en sida? (j/N): ").strip().lower()
        if confirm not in {"j", "ja", "y", "yes"}:
            return
    _print_flights_paged(fetch_query(filt, count=50), None)


def heartbeat() -> bool:
    data = _get(f"{BASE_URL}/heartBeat")
    if data is None:
        print("HeartBeat: inget svar.")
        return False
    if not data:
        print("HeartBeat: OK")
        return True
    raw = data.get("_raw", data)
    print(f"HeartBeat: {raw}")
    return True


def demo() -> None:
    """Call every endpoint once, with a small sample so the demo stays readable."""
    date = datetime.now(_SE_TZ).date().isoformat()
    print(f"Demonstrerar alla endpoints för ARN {date}.")
    heartbeat()
    arrivals = fetch_day("arrivals", "ARN", date)
    print(f"\nArrivals: {len(arrivals)} flyg. Visar de tre första.")
    for index, flight in enumerate(arrivals[:3], start=1):
        _print_flight(flight, index, "ARN")
    departures = fetch_day("departures", "ARN", date)
    print(f"\nDepartures: {len(departures)} flyg. Visar de tre första.")
    for index, flight in enumerate(departures[:3], start=1):
        _print_flight(flight, index, "ARN")
    scheduled = to_odata_date(date)
    if arrivals and arrivals[0].get("flightId"):
        flight_id = re.sub(r"[^A-Z0-9]", "", str(arrivals[0]["flightId"]).upper())
        filt = (
            f"airport eq 'ARN' and scheduled eq '{scheduled}' "
            f"and flightType eq 'A' and flightId eq '{flight_id}'"
        )
        print(f"\nQuery, ett flightnummer: {filt}")
        found = fetch_query(filt, count=5)
        _print_flights_paged(found, "ARN")
    print("\nQuery, tre avgångar från ARN samma datum.")
    sample = fetch_query(
        f"airport eq 'ARN' and scheduled eq '{scheduled}' and flightType eq 'D'",
        count=3,
    )
    _print_flights_paged(sample[:3], "ARN")
    print("\nDemo klar.")


def print_menu() -> None:
    print()
    print("Swedavia FlightInfo API v2 — Python-klient")
    print("—" * 44)
    print("1. Ankomster (arrivals) för en flygplats & datum")
    print("2. Avgångar (departures) för en flygplats & datum")
    print("3. Sök specifikt flightnummer")
    print("4. OData-förfrågan (query endpoint)")
    print("5. HeartBeat – hälsokontroll av API")
    print("6. Demonstrera alla endpoints automatiskt")
    print("q. Avsluta")
    print("Destinationsöversikt ligger i destinationer.py")


def main() -> None:
    _load_dotenv()
    if not os.environ.get("SWEDAVIA_API_KEY"):
        print("Ingen API-nyckel hittades.")
        print("Skapa uppgift/.env med raden SWEDAVIA_API_KEY=din-nyckel")
        print("Nyckeln hämtas på https://apideveloper.swedavia.se/")
    try:
        while True:
            print_menu()
            choice = input("Välj [1-6] eller q: ").strip().lower()
            if choice == "q":
                print("Avslutar.")
                return
            if choice == "1":
                show_day("arrivals")
            elif choice == "2":
                show_day("departures")
            elif choice == "3":
                search_flight()
            elif choice == "4":
                ask_query()
            elif choice == "5":
                heartbeat()
            elif choice == "6":
                demo()
            else:
                print("Välj 1–6 eller q.")
    except (KeyboardInterrupt, EOFError):
        print("\nAvslutar.")


if __name__ == "__main__":
    main()
