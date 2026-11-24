# Swedavia FlightInfo API v2 — Python client

A terminal program that reads live arrivals and departures for Swedavia's 10 airports. It was rebuilt from a screen recording of a finished client: same menu, same four API endpoints, and the same paged flight printout.

The subscription key is yours. Put it in `.env`. The program reads `SWEDAVIA_API_KEY` and does not store a key in the source.

## Setup

```bash
cd uppgift
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```bash
SWEDAVIA_API_KEY=your-own-key
```

Get the key from the [Swedavia Developer Portal](https://apideveloper.swedavia.se/): sign up, open FlightInfo, and subscribe. The free tier is enough. The portal also has the FlightInfo v2 PDF with the fields and the OData rules.

## Run in VS Code

Open the `uppgift` folder, not the parent folder:

```bash
code uppgift
```

The folder already has a virtual environment and a Run and Debug setup. Pick the interpreter `.venv/bin/python` if VS Code asks.

1. Put your key in `.env` (see above).
2. Open Run and Debug.
3. Choose **Flight menu (airport.py)** or **Destinations (destinationer.py)**.
4. Press F5.

The program starts in the integrated terminal, because it asks for input. Type the menu choice there.

From that same terminal you can also run:

```bash
python airport.py
python destinationer.py
```

`airport.py` menu:

1. Arrivals for one airport and date
2. Departures for one airport and date
3. Search one flight number
4. An OData query
5. Heartbeat
6. A short automatic run of every endpoint

Dates accept `YYYY-MM-DD`, `idag`, `imorgon`, `igår`, and `nu`. Airports accept an IATA code (`ARN`) or a city name (`Visby`, `Landvetter`).

Flight lists print 50 at a time. Enter shows the next page, `a` prints the rest, and `q` returns to the menu.

## What each file does

| File | Role |
| --- | --- |
| `airport.py` | Menu, HTTP calls, flight printing |
| `destinationer.py` | Counts cities for arrivals or departures and can filter by city or country |
| `city_country.json` | Offline city-to-country table. No extra API call |
| `build_city_country.py` | Rebuilds that table from the public OurAirports data |

## API calls

Base URL: `https://api.swedavia.se/flightinfo/v2`

The key is sent as the header `Ocp-Apim-Subscription-Key`.

- `GET /{airport}/arrivals/{date}`
- `GET /{airport}/departures/{date}`
- `GET /query?filter=...&continuationtoken=...&count=...`
- `GET /heartBeat`

`date` on the first two calls is `YYYY-MM-DD`. Inside an OData filter, `scheduled` is `YYMMDD`, so 25 February 2026 is `260225`. `flightType` is `A` or `D`. The query endpoint allows one call every two seconds. The client waits when it needs another page. A page token comes back as `continuationtoken`.

Times in the response are UTC. The printout also shows Europe/Stockholm, for example `16:25 UTC → 17:25 CET`. The airport you selected is often missing inside each flight, because the API already scoped the list to that airport. The client prints it as `(ARN)`.

Empty rows with no flight id, no airport name, and no scheduled time are skipped. A flight with no `actualUtc` is counted as still upcoming. Departed and landed flights stay in the list.

## Country lookup

The reference client mapped about 263 cities from a Swedavia statistics spreadsheet. This version maps scheduled-service airports from [OurAirports](https://ourairports.com/data/) so names returned by the API (`Frankfurt`, `London Heathrow`, `Milan`) still resolve offline. Rebuild the file with:

```bash
python build_city_country.py
```

## Checks

```bash
python -m unittest test_airport.py
```

Those tests do not call Swedavia. A live check is menu option 5 (heartbeat), then option 1 for ARN today.
