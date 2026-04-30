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

    def get_bundle(self, session_id, names, start=None, end=None, interval=None, max_points=None, request_id=None):
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
            "coverage": {
                "requested_start": start.isoformat() if start else None,
                "requested_end": end.isoformat() if end else None,
                "query_start": start.isoformat() if start else None,
                "query_end": end.isoformat() if end else None,
                "computed_start": start.isoformat() if start else None,
                "computed_until": end.isoformat() if end else None,
                "complete": True,
                "frame_count": 1,
                "max_points": max_points,
                "request_id": request_id,
            },
            "status": "ready",
            "compute_status": "ready",
            "partial": False,
            "computed_until": end.isoformat() if end else None,
            "progress_ratio": 1,
            "checkpoint_count": 0,
        }

    def get_bundle_by_bars(self, session_id, names, anchor, direction, bar_count, interval=None, max_points=None, request_id=None):
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


class DummyRuntimeService:
    snapshot_interval_seconds = 10

    def live_metadata(self):
        return {
            "mode": "live",
            "run_id": "live-1",
            "status": "running",
            "option_root": "AUTO",
            "underlying_symbol": "MTX",
            "snapshot_count": 12,
            "bar_count": 24,
            "start": "2026-04-22T09:00:00",
            "end": "2026-04-22T10:00:00",
            "selected_option_roots": ["TXX"],
            "available_series": ["pressure_index", "raw_pressure"],
        }

    def live_bars(self):
        return [
            {
                "time": "2026-04-22T10:00:00",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
            }
        ]

    def live_series(self, names):
        return {
            name: [{"time": "2026-04-22T10:00:00", "value": 1}]
            for name in names
        }

    def current_snapshot(self):
        return {"generated_at": "2026-04-22T10:00:00", "expiries": []}

    def live_latest_update(self, *, since=None, names=None, include_bar=True):
        return {
            "updated": True,
            "snapshot_time": "2026-04-22T10:00:00",
            "snapshot": {
                "generated_at": "2026-04-22T10:00:00",
                "pressure_index": 5,
                "raw_pressure": 3,
            },
            "contract_totals": {
                "call": {"cumulative_power": 11, "power_1m_delta": 2},
                "put": {"cumulative_power": -9, "power_1m_delta": -1},
            },
            "series": {
                name: [{"time": "2026-04-22T10:00:00", "value": 1}]
                for name in (names or [])
            },
            "latest_bar": {
                "time": "2026-04-22T10:00:00",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 10,
            } if include_bar else None,
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

    def test_live_snapshot_latest_compact_returns_incremental_payload(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except (ImportError, RuntimeError) as exc:  # pragma: no cover
            self.skipTest(f"fastapi test client unavailable: {exc}")

        app = build_option_power_app(runtime_service=DummyRuntimeService())
        client = TestClient(app)

        response = client.get(
            "/api/option-power/live/snapshot/latest",
            params={
                "compact": "true",
                "since": "2026-04-22T09:59:50",
                "names": "pressure_index,raw_pressure",
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["updated"])
        self.assertEqual(payload["snapshot"]["pressure_index"], 5)
        self.assertEqual(payload["contract_totals"]["call"]["cumulative_power"], 11)
        self.assertEqual(payload["latest_bar"]["time"], "2026-04-22T10:00:00")
        self.assertEqual(sorted(payload["series"].keys()), ["pressure_index", "raw_pressure"])


if __name__ == "__main__":
    unittest.main()
