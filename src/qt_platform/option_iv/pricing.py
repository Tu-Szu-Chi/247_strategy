from __future__ import annotations

from math import erf, exp, isfinite, log, sqrt


MIN_VOL = 0.0001
MAX_VOL = 5.0


def black76_price(
    *,
    forward: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    call_put: str,
    discount_factor: float = 1.0,
) -> float:
    if forward <= 0 or strike <= 0 or time_to_expiry_years <= 0 or volatility <= 0:
        return _intrinsic(forward=forward, strike=strike, call_put=call_put) * discount_factor

    sigma_root_t = volatility * sqrt(time_to_expiry_years)
    if sigma_root_t <= 0:
        return _intrinsic(forward=forward, strike=strike, call_put=call_put) * discount_factor

    d1 = (log(forward / strike) + 0.5 * volatility * volatility * time_to_expiry_years) / sigma_root_t
    d2 = d1 - sigma_root_t
    if call_put == "call":
        return discount_factor * (forward * _normal_cdf(d1) - strike * _normal_cdf(d2))
    if call_put == "put":
        return discount_factor * (strike * _normal_cdf(-d2) - forward * _normal_cdf(-d1))
    raise ValueError("call_put must be one of: call, put")


def implied_volatility(
    *,
    option_price: float,
    forward: float,
    strike: float,
    time_to_expiry_years: float,
    call_put: str,
    discount_factor: float = 1.0,
    max_iterations: int = 80,
    tolerance: float = 1e-6,
) -> float | None:
    if (
        option_price <= 0
        or forward <= 0
        or strike <= 0
        or time_to_expiry_years <= 0
        or discount_factor <= 0
    ):
        return None

    intrinsic = _intrinsic(forward=forward, strike=strike, call_put=call_put) * discount_factor
    if option_price < intrinsic - tolerance:
        return None

    low = MIN_VOL
    high = MAX_VOL
    low_price = black76_price(
        forward=forward,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        volatility=low,
        call_put=call_put,
        discount_factor=discount_factor,
    )
    high_price = black76_price(
        forward=forward,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        volatility=high,
        call_put=call_put,
        discount_factor=discount_factor,
    )
    if option_price < low_price - tolerance or option_price > high_price + tolerance:
        return None

    for _ in range(max_iterations):
        mid = (low + high) / 2
        mid_price = black76_price(
            forward=forward,
            strike=strike,
            time_to_expiry_years=time_to_expiry_years,
            volatility=mid,
            call_put=call_put,
            discount_factor=discount_factor,
        )
        if not isfinite(mid_price):
            return None
        if abs(mid_price - option_price) <= tolerance:
            return mid
        if mid_price > option_price:
            high = mid
        else:
            low = mid

    return (low + high) / 2


def _intrinsic(*, forward: float, strike: float, call_put: str) -> float:
    if call_put == "call":
        return max(forward - strike, 0.0)
    if call_put == "put":
        return max(strike - forward, 0.0)
    raise ValueError("call_put must be one of: call, put")


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))
