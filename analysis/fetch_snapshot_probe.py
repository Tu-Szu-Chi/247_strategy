from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, "src")
from qt_platform.settings import load_settings

settings = load_settings("config/config.yaml")
headers = {"Authorization": f"Bearer {settings.finmind.token}"}
base_url = "https://api.finmindtrade.com/api/v4/data"
params = {"dataset": "TaiwanOptionDaily", "start_date": "2026-03-26"}
query = urlencode(params)
out_dir = Path("analysis")
out_dir.mkdir(exist_ok=True)
for idx in (1, 2):
    ts = time.strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"taiwan_options_snapshot_{ts}_{idx}.txt"
    req = Request(f"{base_url}?{query}", headers=headers, method="GET")
    with urlopen(req, timeout=settings.finmind.timeout_seconds) as resp:
        payload = resp.read().decode("utf-8")
    path.write_text(payload)
    print(path)
    if idx == 1:
        time.sleep(30)



# parameter = {
#     "dataset": "TaiwanOptionDaily",
#     "start_date": "2020-04-01",
# }