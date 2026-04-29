import unittest

from qt_platform.web.app import build_option_power_app


class DummyReplayService:
    def create_session(self, *, start, end):
        return {
            "session_id": "replay-1",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "snapshot_interval_seconds": 5.0,
            "option_root": "AUTO",
            "underlying_symbol": "MTX",
            "selected_option_roots": ["TX4", "TXX"],
            "snapshot_count": 1,
        }

    def get_default_session_metadata(self):
        return None

    def get_bundle(self, session_id, names, start=None, end=None, interval=None):
        return {
            "bars": [
                {
                    "time": start.isoformat() if start else "2026-04-22T09:00:00",
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 10,
                }
            ],
            "series": {name: [] for name in names},
            "status": "ready",
            "compute_status": "ready",
            "partial": False,
            "computed_until": end.isoformat() if end else None,
            "progress_ratio": 1,
            "checkpoint_count": 0,
        }

    def get_bundle_by_bars(self, session_id, names, anchor, direction, bar_count, interval=None):
        return {
            "bars": [
                {
                    "time": anchor.isoformat(),
                    "open": 1,
                    "high": 2,
                    "low": 1,
                    "close": 2,
                    "volume": 10,
                }
            ],
            "series": {name: [] for name in names},
            "status": "ready",
            "compute_status": "ready",
            "partial": False,
            "computed_until": anchor.isoformat(),
            "progress_ratio": 1,
            "checkpoint_count": 0,
            "coverage": {
                "anchor": anchor.isoformat(),
                "direction": direction,
                "interval": interval or "1m",
                "bar_count": bar_count,
                "first_bar_time": anchor.isoformat(),
                "last_bar_time": anchor.isoformat(),
                "has_prev": True,
                "has_next": True,
            },
        }


class WebAppTest(unittest.TestCase):
    def test_replay_session_post_accepts_json_body(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:  # pragma: no cover
            self.skipTest(f"fastapi test client unavailable: {exc}")

        app = build_option_power_app(replay_service=DummyReplayService())
        client = TestClient(app)

        response = client.post(
            "/api/option-power/replay/sessions",
            json={
                "start": "2026-04-22T09:00:00",
                "end": "2026-04-22T09:30:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "replay-1")

    def test_replay_bundle_returns_bars_series_and_status(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:  # pragma: no cover
            self.skipTest(f"fastapi test client unavailable: {exc}")

        app = build_option_power_app(replay_service=DummyReplayService())
        client = TestClient(app)

        response = client.get(
            "/api/option-power/replay/sessions/replay-1/bundle",
            params={
                "names": "pressure_index,raw_pressure",
                "start": "2026-04-22T09:00:00",
                "end": "2026-04-22T09:30:00",
                "interval": "1m",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["bars"]), 1)
        self.assertEqual(sorted(payload["series"].keys()), ["pressure_index", "raw_pressure"])
        self.assertEqual(payload["compute_status"], "ready")
        self.assertFalse(payload["partial"])

    def test_replay_bundle_by_bars_returns_cursor_coverage(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:  # pragma: no cover
            self.skipTest(f"fastapi test client unavailable: {exc}")

        app = build_option_power_app(replay_service=DummyReplayService())
        client = TestClient(app)

        response = client.get(
            "/api/option-power/replay/sessions/replay-1/bundle-by-bars",
            params={
                "names": "pressure_index,raw_pressure",
                "anchor": "2026-04-22T09:00:00",
                "direction": "next",
                "bar_count": "50",
                "interval": "5m",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["bars"]), 1)
        self.assertEqual(payload["coverage"]["direction"], "next")
        self.assertEqual(payload["coverage"]["bar_count"], 50)
        self.assertEqual(payload["coverage"]["interval"], "5m")


if __name__ == "__main__":
    unittest.main()
