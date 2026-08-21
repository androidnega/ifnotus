"""Derive hosting plan resources from monthly price (GHS).

Anchors (by design):
- GHS 30 → 0.25 vCPU / 256 MB
- GHS 70 → 0.50 vCPU / 512 MB

Other prices interpolate/extrapolate, then snap to clean sizes.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Preferred RAM sizes (MB) for clean packaging.
_RAM_SNAPS_MB = (
    128,
    192,
    256,
    384,
    512,
    768,
    1024,
    1536,
    2048,
    3072,
    4096,
    6144,
    8192,
    12288,
    16384,
    24576,
    32768,
)


def _snap_ram_mb(raw: float) -> int:
    return min(_RAM_SNAPS_MB, key=lambda s: abs(s - raw))


def _quantize_cpu(raw: float) -> Decimal:
    # 0.05 steps, minimum 0.1
    stepped = round(max(0.1, min(16.0, raw)) * 20) / 20
    return Decimal(str(stepped)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def resources_from_price(price_monthly: Decimal | float | int | str) -> dict[str, Decimal | int]:
    """Return cpu_cores, ram_gb, storage_gb, bandwidth_tb, ai_credits from price."""
    price = float(Decimal(str(price_monthly)))
    if price < 0:
        price = 0.0

    # Linear through (30 → 0.25 CPU / 256 MB) and (70 → 0.50 CPU / 512 MB).
    cpu_raw = 0.25 + (price - 30.0) * (0.25 / 40.0)
    ram_raw_mb = 256.0 + (price - 30.0) * (256.0 / 40.0)

    cpu = _quantize_cpu(cpu_raw)
    ram_mb = _snap_ram_mb(max(128.0, min(32768.0, ram_raw_mb)))
    ram_gb = (Decimal(ram_mb) / Decimal(1024)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Storage stays modest: ₵30 → 2 GB, ₵70 → 4 GB (then snap).
    storage_raw = 2.0 + (price - 30.0) * (2.0 / 40.0)
    storage_snaps = (2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50)
    storage_gb = min(storage_snaps, key=lambda s: abs(s - max(2.0, min(50.0, storage_raw))))

    bandwidth_tb = max(
        Decimal("0.5"),
        (Decimal(str(price)) / Decimal("70")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
    )
    ai_credits = max(5, int(round(price / 5.0)))

    return {
        "cpu_cores": cpu,
        "ram_gb": ram_gb,
        "storage_gb": storage_gb,
        "bandwidth_tb": bandwidth_tb,
        "ai_credits": ai_credits,
    }
