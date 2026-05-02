import tempfile
import textwrap
import unittest
from pathlib import Path

from qt_platform.settings import load_settings


class SettingsTest(unittest.TestCase):
    def test_load_settings_reads_kronos_section(self) -> None:
        config_text = textwrap.dedent(
            """
            app:
              timezone: "Asia/Taipei"

            database:
              url: "sqlite:///local.db"

            finmind:
              base_url: "https://api.finmindtrade.com/api/v4"
              token_env: "FINMIND_TOKEN"
              rps_limit: 1
              retry_limit: 2
              backoff_factor: 2.0
              timeout_seconds: 30

            reporting:
              output_dir: "reports"

            shioaji:
              api_key_env: "SH_API_KEY"
              secret_key_env: "SH_SECRET_KEY"

            sync:
              registry_path: "config/symbols.csv"

            kronos:
              enabled: true
              target:
                - "10m:50"
                - "20m:100"
              lookback: 300
              sample_count: 128
              interval_minutes: 5
              temperature: 1.0
              top_k: 0
              top_p: 0.9
              model: "config-model"
              tokenizer: "config-tokenizer"
              model_revision: "rev-a"
              tokenizer_revision: "rev-b"
              device: "cuda:0"
              max_context: 1024
            """
        ).strip()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text(config_text, encoding="utf-8")
            settings = load_settings(path)

        self.assertTrue(settings.kronos.enabled)
        self.assertEqual(settings.kronos.target, ["10m:50", "20m:100"])
        self.assertEqual(settings.kronos.lookback, 300)
        self.assertEqual(settings.kronos.sample_count, 128)
        self.assertEqual(settings.kronos.interval_minutes, 5)
        self.assertEqual(settings.kronos.model, "config-model")
        self.assertEqual(settings.kronos.tokenizer, "config-tokenizer")
        self.assertEqual(settings.kronos.device, "cuda:0")
        self.assertEqual(settings.kronos.max_context, 1024)


if __name__ == "__main__":
    unittest.main()
