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


if __name__ == "__main__":
    unittest.main()
