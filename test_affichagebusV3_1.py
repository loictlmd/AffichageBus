"""Tests hors réseau : python3 -m unittest -v test_affichagebusV3_1.py"""
import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import affichagebusV3_1 as app


def geo(rows):
    return {"features": [{"properties": row} for row in rows]}


def bus(stamp, **kwargs):
    return {"code_ligne": "L5", "nom_station": "SOLFERINO", "sens_ligne": app.DIRECTIONS["L5"][0],
            "heure_estimee_depart": stamp, **kwargs}


class DataTests(unittest.TestCase):
    def test_mel_uses_explicit_offset_in_sort_key(self):
        item = bus("2026-10-02T11:47:19Z", cle_tri="HAUBOURDIN LE PARC/SOLFERINO/2026-10-02T11:47:19.000+02:00")
        dt = app.parse_bus_departure(item)
        self.assertEqual(dt.hour, 11)
        self.assertEqual(dt.utcoffset(), timedelta(hours=2))
        now = app.parse_departure("2026-10-02T11:46:57+02:00")
        self.assertEqual(app.remaining_minutes(dt, now), 1)

    def test_mel_missing_sort_key_does_not_add_two_hours(self):
        self.assertEqual(app.parse_bus_departure(bus("2026-10-02T11:47:19Z")).hour, 11)
        winter = app.parse_bus_departure(bus("2026-12-02T11:47:19Z"))
        self.assertEqual(winter.hour, 11)
        self.assertEqual(winter.utcoffset(), timedelta(hours=1))

    def test_real_utc_sort_key_is_converted(self):
        item = bus("2026-10-02T09:47:19Z", cle_tri="DEST/SOLFERINO/2026-10-02T09:47:19+00:00")
        self.assertEqual(app.parse_bus_departure(item).hour, 11)

    def test_source_specific_fallback_leaves_events_untouched(self):
        event = app.parse_events([{"date":"2026-10-02", "time":"13:30", "title":"Test", "association":"BDE"}])[0]
        self.assertEqual(event["start"].hour, 13)
        with patch.object(app, "MEL_BUS_Z_IS_LOCAL", False):
            self.assertEqual(app.parse_bus_departure(bus("2026-10-02T09:47:19Z")).hour, 11)

    def test_sidebar_keeps_actual_destinations(self):
        now = app.parse_departure("2026-10-02T11:00:00+02:00")
        data = {("L5", "MARCQ"): (now + timedelta(minutes=8),), ("L5", "LA MADELEINE"): (now + timedelta(minutes=3),)}
        rows = app.line_departures(data, "L5", now)
        self.assertEqual([direction for _, direction in rows], ["LA MADELEINE", "MARCQ"])

    def test_utc_is_converted_to_paris(self):
        self.assertEqual(app.parse_departure("2026-07-02T10:00:00Z").hour, 12)
        self.assertEqual(app.parse_departure("2026-01-02T10:00:00Z").hour, 11)

    def test_midnight(self):
        now = app.parse_departure("2026-10-02T23:58:00+02:00")
        dt = app.parse_departure("2026-10-03T00:03:00+02:00")
        self.assertEqual(app.remaining_minutes(dt, now), 5)
        self.assertEqual(app.upcoming((dt,), now), (dt,))

    def test_dst_spring(self):
        now = app.parse_departure("2026-03-29T01:55:00+01:00")
        dt = app.parse_departure("2026-03-29T03:05:00+02:00")
        self.assertEqual(app.remaining_minutes(dt, now), 10)

    def test_dst_fall_keeps_both_departures(self):
        result = app.parse_bus(geo([bus("2026-10-25T02:30:00+02:00"), bus("2026-10-25T02:30:00+01:00")]))
        items = result[("L5", app.DIRECTIONS["L5"][0])]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].timestamp() - items[0].timestamp(), 3600)

    def test_filter_sort_deduplicate_and_bad_records(self):
        rows = [bus("2026-10-02T12:10:00+02:00"), bus("bad"), bus("2026-10-02T12:05:00+02:00", nom_station="Solférino"),
                bus("2026-10-02T12:10:00+02:00"), bus("2026-10-02T12:01:00+02:00", nom_station="AUTRE")]
        items = app.parse_bus(geo(rows))[("L5", app.DIRECTIONS["L5"][0])]
        self.assertEqual([dt.minute for dt in items], [5, 10])

    def test_old_times_filtered_before_selecting_two(self):
        now = app.parse_departure("2026-10-02T12:10:00+02:00")
        times = tuple(now + timedelta(minutes=n) for n in (-20, -10, 3, 6))
        self.assertEqual(app.upcoming(times, now), times[2:])

    def test_empty_bus_response_clears_previous_data(self):
        store = app.DataStore()
        store.publish("bus", app.parse_bus(geo([bus("2026-10-02T12:10:00+02:00")])))
        store.publish("bus", app.parse_bus(geo([])))
        self.assertFalse(any(store.snapshot()[1]["bus"].data.values()))

    def test_failure_retains_last_success_and_is_source_specific(self):
        store = app.DataStore()
        stamp = app.parse_departure("2026-10-02T12:00:00+02:00")
        data = {"bikes": 0, "spaces": 22}
        store.publish("vlille", data, stamp)
        store.fail("vlille", "Network timeout")
        store.publish("actual", {"temperature": 15})
        state = store.snapshot()[1]["vlille"]
        self.assertEqual(state.data, data)
        self.assertEqual(state.updated_at, stamp)
        self.assertEqual(app.status(state, "vlille", stamp), "Données anciennes")
        self.assertIsNotNone(state.error)

    def test_vlille_missing_differs_from_zero(self):
        row = {"nom": "Palais Rameau", "nb_velos_dispo": 0, "nb_places_dispo": 25}
        self.assertEqual(app.parse_vlille(geo([row]))["bikes"], 0)
        with self.assertRaises(ValueError):
            app.parse_vlille(geo([]))

    def test_events_sort_and_skip_invalid(self):
        events = [{"date": "2026-10-04", "time": "18:00", "title": "B", "association": "BDE"},
                  {"date": "2026-10-03", "time": "15:00", "title": "A", "association": "BDE"}, {"bad": 1}]
        self.assertEqual([e["title"] for e in app.parse_events(events)], ["A", "B"])
        with self.assertRaises(ValueError):
            app.parse_events({"error": "unavailable"})

    def test_next_event_is_future_and_today_events_remain(self):
        now = app.parse_departure("2026-10-02T12:00:00+02:00")
        rows = tuple({"start": now + timedelta(hours=h), "title": str(h)} for h in (-25, -1, 2))
        self.assertEqual(len(app.visible_events(rows, now)), 2)
        self.assertEqual(app.next_event(rows, now)["title"], "2")

    def test_forecast_dates_and_incomplete_fields(self):
        result = app.parse_forecast({"daily": {"time": ["2026-10-03"], "temperature_2m_max": [18]}})
        self.assertEqual(result[0]["date"].day, 3)
        self.assertIsNone(result[0]["min"])
        self.assertEqual(app.weather_kind(0), ("sunny", "Ensoleillé"))
        self.assertEqual(app.weather_kind(73), ("snow", "Neige"))

    def test_pagination(self):
        base = "https://example.org/items"
        pages = [dict(geo([bus("2026-10-02T12:00:00+02:00")]), links=[{"rel": "next", "href": "?page=2"}]), geo([])]
        with patch.object(app, "get_json", side_effect=pages) as mocked:
            result = app.get_geojson(None, base)
        self.assertEqual(len(result["features"]), 1)
        self.assertEqual(mocked.call_args_list[1].args[1], base + "?page=2")


class DisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.pygame.display.init()
        app.pygame.font.init()
        app.pygame.display.set_mode((1920, 1080))

    @classmethod
    def tearDownClass(cls):
        app.pygame.quit()

    def test_all_pages_empty_loaded_and_stale_at_three_resolutions(self):
        now = app.parse_departure("2026-10-02T12:00:00+02:00")
        loaded = app.demo_store(now)
        loaded.publish("events", tuple({"start": now + timedelta(days=i), "title": "Un titre très long " * 15,
                                         "association": "Une association très longue " * 8} for i in range(14)), now)
        old = app.demo_store(now - timedelta(days=2))
        for name in app.PERIODS:
            old.fail(name, "offline")
        for size in ((1920, 1080), (1280, 720), (1024, 768)):
            renderer = app.Renderer(app.pygame.Surface(size))
            for store in (app.DataStore(), loaded, old):
                for page in range(4):
                    for elapsed in (2, 7):
                        renderer.draw(page, store.snapshot()[1], now, elapsed, event_sheet=2)
        self.assertLessEqual(renderer.c.raster.cache_info().currsize, 512)

    def test_adaptive_agenda_one_to_seven_events(self):
        now = app.parse_departure("2026-10-02T11:39:00+02:00")
        renderer = app.Renderer(app.pygame.Surface((1920, 1080)))
        for count in range(1, 8):
            store = app.demo_store(now)
            store.publish("events", tuple({"start": now + timedelta(hours=i+1), "title": "Un titre très long " * 10,
                                            "association": "Association au long nom " * 6} for i in range(count)), now)
            for sheet in (0, 1):
                for elapsed in (2, 7):
                    renderer.draw(0, store.snapshot()[1], now, elapsed, event_sheet=sheet)

    def test_weather_images_take_priority_over_vector_drawing(self):
        canvas = app.Canvas(app.pygame.Surface((1920, 1080)))
        with patch.object(canvas, "image", return_value=True) as image, patch.object(canvas, "circle") as draw:
            canvas.weather_icon("sunny", 0, 0, 100)
            image.assert_called_once_with("sunny.png", (0, 0, 100, 100))
            draw.assert_not_called()

    def test_footer_neither_loads_logo_nor_draws_progress(self):
        renderer = app.Renderer(app.pygame.Surface((1920, 1080)))
        with patch.object(renderer.c, "image") as image, patch.object(renderer.c, "rect") as rect:
            renderer.footer(0, False)
            image.assert_not_called()
            rect.assert_not_called()

    def test_slow_bus_does_not_block_other_sources_or_display(self):
        gate, entered = threading.Event(), threading.Event()
        now = app.parse_departure("2026-10-02T12:00:00+02:00")
        def fake_geo(_session, url):
            if url == app.API_URL:
                entered.set()
                gate.wait(3)
                return geo([])
            return geo([{"nom": "PALAIS RAMEAU", "nb_velos_dispo": 2, "nb_places_dispo": 4}])
        def fake_json(_session, url):
            if url == app.ACTUAL_URL:
                return {"current": {"temperature_2m": 20}}
            if url == app.METEO_URL:
                return {"daily": {"time": ["2026-10-03"], "temperature_2m_max": [18]}}
            return []
        store, fetcher = app.DataStore(), None
        with patch.object(app, "get_geojson", side_effect=fake_geo), patch.object(app, "get_json", side_effect=fake_json):
            try:
                fetcher = app.Fetcher(store)
                fetcher.start()
                self.assertTrue(entered.wait(1))
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline and store.snapshot()[1]["actual"].data is None:
                    threading.Event().wait(0.01)
                _, sources = store.snapshot()
                self.assertIsNotNone(sources["actual"].data)
                self.assertIsNone(sources["bus"].data)
                app.Renderer(app.pygame.Surface((1280, 720))).draw(1, sources, now, 0)
                self.assertFalse(gate.is_set())
            finally:
                gate.set()
                if fetcher:
                    fetcher.stop()


if __name__ == "__main__":
    unittest.main()
