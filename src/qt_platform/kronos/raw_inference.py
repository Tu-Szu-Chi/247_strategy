from __future__ import annotations

from typing import Any


def predict_raw_paths(
    predictor: Any,
    *,
    df: Any,
    x_timestamp: Any,
    y_timestamp: Any,
    pred_len: int,
    temperature: float = 1.0,
    top_k: int = 0,
    top_p: float = 0.9,
    sample_count: int = 1,
    verbose: bool = False,
) -> Any:
    np = _require_numpy()
    calc_time_stamps = _kronos_time_stamp_function()

    if not all(col in df.columns for col in predictor.price_cols):
        raise ValueError(f"Price columns {predictor.price_cols} not found in DataFrame.")

    df = df.copy()
    if predictor.vol_col not in df.columns:
        df[predictor.vol_col] = 0.0
        df[predictor.amt_vol] = 0.0
    if predictor.amt_vol not in df.columns and predictor.vol_col in df.columns:
        df[predictor.amt_vol] = df[predictor.vol_col] * df[predictor.price_cols].mean(axis=1)

    feature_cols = predictor.price_cols + [predictor.vol_col, predictor.amt_vol]
    if df[feature_cols].isnull().values.any():
        raise ValueError("Input DataFrame contains NaN values in price or volume columns.")

    x_time_df = calc_time_stamps(x_timestamp)
    y_time_df = calc_time_stamps(y_timestamp)

    x = df[feature_cols].values.astype("float32")
    x_stamp = x_time_df.values.astype("float32")
    y_stamp = y_time_df.values.astype("float32")

    x_mean, x_std = np.mean(x, axis=0), np.std(x, axis=0)
    x = (x - x_mean) / (x_std + 1e-5)
    x = np.clip(x, -predictor.clip, predictor.clip)

    x = x[np.newaxis, :]
    x_stamp = x_stamp[np.newaxis, :]
    y_stamp = y_stamp[np.newaxis, :]

    paths = _generate_raw(
        predictor,
        x,
        x_stamp,
        y_stamp,
        pred_len=pred_len,
        temperature=temperature,
        top_k=top_k,
        top_p=top_p,
        sample_count=sample_count,
        verbose=verbose,
    )
    paths = paths.squeeze(0)
    return paths * (x_std + 1e-5) + x_mean


def _generate_raw(
    predictor: Any,
    x: Any,
    x_stamp: Any,
    y_stamp: Any,
    *,
    pred_len: int,
    temperature: float,
    top_k: int,
    top_p: float,
    sample_count: int,
    verbose: bool,
) -> Any:
    np = _require_numpy()
    torch = _require_torch()
    x_tensor = torch.from_numpy(np.array(x).astype("float32")).to(predictor.device)
    x_stamp_tensor = torch.from_numpy(np.array(x_stamp).astype("float32")).to(predictor.device)
    y_stamp_tensor = torch.from_numpy(np.array(y_stamp).astype("float32")).to(predictor.device)
    paths = auto_regressive_inference_raw(
        predictor.tokenizer,
        predictor.model,
        x_tensor,
        x_stamp_tensor,
        y_stamp_tensor,
        predictor.max_context,
        pred_len,
        predictor.clip,
        temperature,
        top_k,
        top_p,
        sample_count,
        verbose,
    )
    return paths[:, :, -pred_len:, :]


def auto_regressive_inference_raw(
    tokenizer: Any,
    model: Any,
    x: Any,
    x_stamp: Any,
    y_stamp: Any,
    max_context: int,
    pred_len: int,
    clip: float = 5,
    temperature: float = 1.0,
    top_k: int = 0,
    top_p: float = 0.99,
    sample_count: int = 5,
    verbose: bool = False,
) -> Any:
    torch = _require_torch()
    trange = _progress_range_function()
    sample_from_logits = _kronos_sample_function()

    with torch.no_grad():
        x = torch.clip(x, -clip, clip)

        device = x.device
        x = x.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, x.size(1), x.size(2)).to(device)
        x_stamp = x_stamp.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, x_stamp.size(1), x_stamp.size(2)).to(device)
        y_stamp = y_stamp.unsqueeze(1).repeat(1, sample_count, 1, 1).reshape(-1, y_stamp.size(1), y_stamp.size(2)).to(device)

        x_token = tokenizer.encode(x, half=True)

        initial_seq_len = x.size(1)
        batch_size = x_token[0].size(0)
        total_seq_len = initial_seq_len + pred_len
        full_stamp = torch.cat([x_stamp, y_stamp], dim=1)

        generated_pre = x_token[0].new_empty(batch_size, pred_len)
        generated_post = x_token[1].new_empty(batch_size, pred_len)

        pre_buffer = x_token[0].new_zeros(batch_size, max_context)
        post_buffer = x_token[1].new_zeros(batch_size, max_context)
        buffer_len = min(initial_seq_len, max_context)
        if buffer_len > 0:
            start_idx = max(0, initial_seq_len - max_context)
            pre_buffer[:, :buffer_len] = x_token[0][:, start_idx:start_idx + buffer_len]
            post_buffer[:, :buffer_len] = x_token[1][:, start_idx:start_idx + buffer_len]

        iterator = trange(pred_len) if verbose else range(pred_len)
        for i in iterator:
            current_seq_len = initial_seq_len + i
            window_len = min(current_seq_len, max_context)

            if current_seq_len <= max_context:
                input_tokens = [
                    pre_buffer[:, :window_len],
                    post_buffer[:, :window_len],
                ]
            else:
                input_tokens = [pre_buffer, post_buffer]

            context_end = current_seq_len
            context_start = max(0, context_end - max_context)
            current_stamp = full_stamp[:, context_start:context_end, :].contiguous()

            s1_logits, context = model.decode_s1(input_tokens[0], input_tokens[1], current_stamp)
            s1_logits = s1_logits[:, -1, :]
            sample_pre = sample_from_logits(
                s1_logits,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                sample_logits=True,
            )

            s2_logits = model.decode_s2(context, sample_pre)
            s2_logits = s2_logits[:, -1, :]
            sample_post = sample_from_logits(
                s2_logits,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                sample_logits=True,
            )

            generated_pre[:, i] = sample_pre.squeeze(-1)
            generated_post[:, i] = sample_post.squeeze(-1)

            if current_seq_len < max_context:
                pre_buffer[:, current_seq_len] = sample_pre.squeeze(-1)
                post_buffer[:, current_seq_len] = sample_post.squeeze(-1)
            else:
                pre_buffer.copy_(torch.roll(pre_buffer, shifts=-1, dims=1))
                post_buffer.copy_(torch.roll(post_buffer, shifts=-1, dims=1))
                pre_buffer[:, -1] = sample_pre.squeeze(-1)
                post_buffer[:, -1] = sample_post.squeeze(-1)

        full_pre = torch.cat([x_token[0], generated_pre], dim=1)
        full_post = torch.cat([x_token[1], generated_post], dim=1)

        context_start = max(0, total_seq_len - max_context)
        input_tokens = [
            full_pre[:, context_start:total_seq_len].contiguous(),
            full_post[:, context_start:total_seq_len].contiguous(),
        ]
        z = tokenizer.decode(input_tokens, half=True)
        z = z.reshape(-1, sample_count, z.size(1), z.size(2))
        return z.cpu().numpy()


def _require_numpy() -> Any:
    try:
        import numpy as np
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional kronos deps
        raise RuntimeError("numpy is required for Kronos raw inference.") from exc
    return np


def _require_torch() -> Any:
    try:
        import torch
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional kronos deps
        raise RuntimeError("torch is required for Kronos raw inference.") from exc
    return torch


def _progress_range_function() -> Any:
    try:
        from tqdm import trange
    except ModuleNotFoundError:  # pragma: no cover - depends on optional kronos deps
        return range
    return trange


def _kronos_sample_function() -> Any:
    try:
        from model.kronos import sample_from_logits
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional kronos deps
        raise RuntimeError("Kronos model package is not importable.") from exc
    return sample_from_logits


def _kronos_time_stamp_function() -> Any:
    try:
        from model.kronos import calc_time_stamps
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional kronos deps
        raise RuntimeError("Kronos model package is not importable.") from exc
    return calc_time_stamps
