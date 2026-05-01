from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from qt_platform.domain import Bar
from qt_platform.kronos.features import bars_to_kronos_frame, bar_timestamps, future_timestamps
from qt_platform.kronos.raw_inference import predict_raw_paths


DEFAULT_KRONOS_MODEL_ID = "NeoQuasar/Kronos-mini"
DEFAULT_KRONOS_TOKENIZER_ID = "NeoQuasar/Kronos-Tokenizer-2k"


@dataclass(frozen=True)
class KronosModelConfig:
    model_id: str = DEFAULT_KRONOS_MODEL_ID
    tokenizer_id: str = DEFAULT_KRONOS_TOKENIZER_ID
    model_revision: str | None = None
    tokenizer_revision: str | None = None
    device: str | None = None
    max_context: int = 512
    kronos_root: Path | None = None


class KronosPathPredictor:
    def __init__(self, config: KronosModelConfig | None = None) -> None:
        self.config = config or KronosModelConfig()
        Kronos, KronosTokenizer, KronosPredictor = _load_kronos_classes(self.config.kronos_root)
        tokenizer_kwargs = _revision_kwargs(self.config.tokenizer_revision)
        model_kwargs = _revision_kwargs(self.config.model_revision)
        tokenizer = KronosTokenizer.from_pretrained(self.config.tokenizer_id, **tokenizer_kwargs)
        model = Kronos.from_pretrained(self.config.model_id, **model_kwargs)
        tokenizer.eval()
        model.eval()
        self._predictor = KronosPredictor(
            model,
            tokenizer,
            device=self.config.device,
            max_context=self.config.max_context,
        )

    def predict_paths(
        self,
        bars: Sequence[Bar],
        *,
        pred_len: int,
        sample_count: int,
        temperature: float = 1.0,
        top_k: int = 0,
        top_p: float = 0.9,
        verbose: bool = False,
    ) -> Any:
        if pred_len <= 0:
            raise ValueError("pred_len must be positive")
        if sample_count <= 0:
            raise ValueError("sample_count must be positive")
        return predict_raw_paths(
            self._predictor,
            df=bars_to_kronos_frame(bars),
            x_timestamp=bar_timestamps(bars),
            y_timestamp=future_timestamps(bars, pred_len=pred_len),
            pred_len=pred_len,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            sample_count=sample_count,
            verbose=verbose,
        )


def _load_kronos_classes(kronos_root: Path | None) -> tuple[Any, Any, Any]:
    root = kronos_root or Path(__file__).resolve().parents[3] / "Kronos"
    if not root.exists():
        raise RuntimeError(f"Kronos repository not found at {root}")
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional kronos deps
        raise RuntimeError("Kronos dependencies are not installed. Install the kronos optional extra.") from exc
    return Kronos, KronosTokenizer, KronosPredictor


def _revision_kwargs(revision: str | None) -> dict[str, str]:
    return {"revision": revision} if revision else {}
