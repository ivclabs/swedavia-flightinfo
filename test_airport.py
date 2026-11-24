"""Offline checks for parsing, printing, and the country lookup. No API key needed."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import airport
import destinationer


class ParseTests(unittest.TestCase):
    def test_airport_codes_and_city_names(self) -> None:
        self.assertEqual(airport.resolve_airport("arn"), "ARN")
        self.assertEqual(airport.resolve_airport("Visby"), "VBY")
        self.assertEqual(airport.resolve_airport("göteborg"), "GOT")
        self.assertEqual(airport.resolve_airport("Landvetter"), "GOT")
        self.assertIsNone(airport.resolve_airport("XYZ"))

    def test_dates(self) -> None:
        self.assertEqual(airport.parse_date("2026-02-25"), "2026-02-25")
        self.assertEqual(airport.to_odata_date("2026-02-25"), "260225")
        self.assertIsNone(airport.parse_date("25/02/2026"))
        self.assertIsNotNone(airport.parse_date("idag"))
        self.assertIsNotNone(airport.parse_date("imorgon"))

    def test_time_zones(self) -> None:
        self.assertEqual(airport._fmt_time(None), "-")
        self.assertEqual(airport._fmt_time("2026-02-25T16:25:00Z"), "16:25 UTC → 17:25 CET")
        self.assertEqual(airport._fmt_time("2026-07-01T10:00:00Z"), "10:00 UTC → 12:00 CEST")

    def test_valid_and_upcoming(self) -> None:
        ghost = {"flightId": "", "arrivalTime": {}}
        self.assertFalse(airport._is_valid_flight(ghost))
        landed = {"flightId": "SK1", "arrivalTime": {"scheduledUtc": "2026-02-25T10:00:00Z", "actualUtc": "2026-02-25T10:05:00Z"}}
        self.assertTrue(airport._is_valid_flight(landed))
        self.assertFalse(airport._is_upcoming(landed))
        planned = {"flightId": "SK2", "departureTime": {"scheduledUtc": "2026-02-25T10:00:00Z"}}
        self.assertTrue(airport._is_upcoming(planned))

    def test_query_wrapper_is_unwrapped(self) -> None:
        wrapped = {"arrival": {"flightId": "SK1", "arrivalTime": {"scheduledUtc": "2026-02-25T10:00:00Z"}}, "departure": None}
        flights = airport._unwrap_flights(wrapped)
        self.assertEqual([item["flightId"] for item in flights], ["SK1"])


class PrintTests(unittest.TestCase):
    def test_home_airport_fills_the_missing_side(self) -> None:
        flight = {
            "flightId": "SK532",
            "departureAirportEnglish": "London Heathrow",
            "airlineOperator": {"name": "SAS Scandinavian Airlines", "iata": "SK"},
            "arrivalTime": {"scheduledUtc": "2026-02-25T16:25:00Z"},
            "locationAndStatus": {"terminal": "5", "gate": "", "flightLegStatusEnglish": "Scheduled"},
            "baggage": {"baggageClaimUnit": "3"},
            "diIndicator": "I",
        }
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            airport._print_flight(flight, 50, "ARN")
        text = buffer.getvalue()
        self.assertIn("[50] → SK532 | SAS Scandinavian Airlines (SK)", text)
        self.assertIn("From    : London Heathrow", text)
        self.assertIn("To      : (ARN)", text)
        self.assertIn("Sched   : 16:25 UTC → 17:25 CET", text)
        self.assertIn("Baggage : 3", text)
        self.assertIn("D/I     : I", text)

    def test_paging_stops_when_q_is_pressed(self) -> None:
        flights = []
        for number in range(60):
            flights.append(
                {
                    "flightId": f"SK{100 + number}",
                    "departureAirportEnglish": "Oslo",
                    "arrivalTime": {"scheduledUtc": "2026-02-25T10:00:00Z"},
                    "airlineOperator": {"name": "SAS", "iata": "SK"},
                }
            )
        buffer = io.StringIO()
        with patch("builtins.input", return_value="q"), redirect_stdout(buffer):
            airport._print_flights_paged(flights, "ARN")
        text = buffer.getvalue()
        self.assertIn("Visar 50/60", text)
        self.assertIn("Avbröt efter 50 flights.", text)
        self.assertIn("SK100", text)
        self.assertNotIn("SK150", text)


class CountryTests(unittest.TestCase):
    def test_known_cities(self) -> None:
        self.assertEqual(destinationer.lookup_country("Frankfurt"), "Germany")
        self.assertEqual(destinationer.lookup_country("Paris"), "France")
        self.assertEqual(destinationer.lookup_country("Milan"), "Italy")
        self.assertEqual(destinationer.lookup_country("London Heathrow"), "United Kingdom")
        self.assertEqual(destinationer.lookup_country("Krakow"), "Poland")

    def test_country_filter_keeps_matching_cities(self) -> None:
        counts = {"Madrid": 4, "Barcelona": 2, "Oslo": 3}
        rows = destinationer.filter_rows(counts, "Spain")
        self.assertEqual([city for city, _count, _country in rows], ["Madrid", "Barcelona"])


class FetchTests(unittest.TestCase):
    def test_continuation_token_is_followed_and_ghosts_are_dropped(self) -> None:
        pages = [
            {
                "flights": [
                    {"flightId": "SK1", "arrivalTime": {"scheduledUtc": "2026-02-25T10:00:00Z"}},
                    {"flightId": "", "arrivalTime": {}},
                ],
                "continuationtoken": "page-2",
            },
            {
                "flights": [
                    {
                        "arrival": {"flightId": "SK2", "arrivalTime": {"scheduledUtc": "2026-02-25T11:00:00Z"}},
                        "departure": None,
                    }
                ]
            },
        ]

        def fake_get(url: str, params: dict | None = None) -> dict:
            self.assertIn("/ARN/arrivals/2026-02-25", url)
            if not pages:
                return {}
            if len(pages) == 1:
                self.assertEqual((params or {}).get("continuationtoken"), "page-2")
            return pages.pop(0)

        with patch.object(airport, "_get", side_effect=fake_get):
            flights = airport.fetch_day("arrivals", "ARN", "2026-02-25")
        self.assertEqual([flight["flightId"] for flight in flights], ["SK1", "SK2"])


class KeyTests(unittest.TestCase):
    def test_missing_key_does_not_call_the_network(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch("airport.requests.get") as get:
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = airport._get("https://api.swedavia.se/flightinfo/v2/heartBeat")
        self.assertIsNone(result)
        get.assert_not_called()
        self.assertIn("Saknar API-nyckel", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
