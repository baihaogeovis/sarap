"""VV 自适应阈值：KI 或 Otsu + 夹逼 + 双峰失败回退 T_default。纯 numpy。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ThresholdResult:
    T: float
    T_auto: float | None
    T_default: float
    clamp: tuple[float, float]
    source: str  # auto / auto_clamped / default
    method: str | None  # ki / otsu / None
    n_valid: int
    bimodal: bool
    reason: str


def _histogram(values: np.ndarray, bin_edges: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    counts, edges = np.histogram(values, bins=bin_edges)
    centers = 0.5 * (edges[:-1] + edges[1:])
    return counts.astype(np.float64), centers


def otsu_threshold(counts: np.ndarray, centers: np.ndarray) -> tuple[float, float]:
    """返回 (阈值, 类间方差)。阈值取对应 bin 的中心。"""
    total = counts.sum()
    if total <= 0:
        raise ValueError("empty histogram")
    prob = counts / total
    omega = np.cumsum(prob)
    mu = np.cumsum(prob * centers)
    mu_t = mu[-1]
    # 避免除零
    omega_0 = np.clip(omega[:-1], 1e-12, 1.0)
    omega_1 = np.clip(1.0 - omega[:-1], 1e-12, 1.0)
    mu_0 = mu[:-1] / omega_0
    mu_1 = (mu_t - mu[:-1]) / omega_1
    sigma_b = omega_0 * omega_1 * (mu_0 - mu_1) ** 2
    idx = int(np.argmax(sigma_b))
    return float(centers[idx]), float(sigma_b[idx])


def kittler_illingworth(counts: np.ndarray, centers: np.ndarray) -> tuple[float, float]:
    """KI 最小误差阈值。返回 (阈值, 最小准则值)。"""
    total = counts.sum()
    if total <= 0:
        raise ValueError("empty histogram")
    best_j = np.inf
    best_t = float(centers[len(centers) // 2])
    cum_n = np.cumsum(counts)
    cum_x = np.cumsum(counts * centers)
    cum_x2 = np.cumsum(counts * centers * centers)
    for i in range(1, len(counts) - 1):
        n1 = cum_n[i]
        n2 = total - n1
        if n1 < 2 or n2 < 2:
            continue
        mu1 = cum_x[i] / n1
        mu2 = (cum_x[-1] - cum_x[i]) / n2
        var1 = max(cum_x2[i] / n1 - mu1 * mu1, 1e-6)
        var2 = max((cum_x2[-1] - cum_x2[i]) / n2 - mu2 * mu2, 1e-6)
        p1, p2 = n1 / total, n2 / total
        j = (
            1.0
            + 2.0 * (p1 * np.log(np.sqrt(var1)) + p2 * np.log(np.sqrt(var2)))
            - 2.0 * (p1 * np.log(p1) + p2 * np.log(p2))
        )
        if j < best_j:
            best_j = j
            best_t = float(centers[i])
    return best_t, float(best_j)


def _class_stats(values: np.ndarray, t: float) -> tuple[int, int, float, float]:
    low = values[values < t]
    high = values[values >= t]
    n1, n2 = int(low.size), int(high.size)
    mu1 = float(low.mean()) if n1 else float("nan")
    mu2 = float(high.mean()) if n2 else float("nan")
    return n1, n2, mu1, mu2


def is_bimodal(
    values: np.ndarray,
    t: float,
    *,
    min_samples: int = 64,
    min_class_fraction: float = 0.05,
    min_separation_db: float = 2.0,
) -> tuple[bool, str]:
    n = int(values.size)
    if n < min_samples:
        return False, f"有效像元过少({n}<{min_samples})"
    n1, n2, mu1, mu2 = _class_stats(values, t)
    if n1 == 0 or n2 == 0:
        return False, "单峰或阈值未切开两类"
    frac = min(n1, n2) / n
    if frac < min_class_fraction:
        return False, f"一类占比过低({frac:.3f})"
    if not np.isfinite(mu1) or not np.isfinite(mu2):
        return False, "无法估计两类均值"
    sep = abs(mu2 - mu1)
    if sep < min_separation_db:
        return False, f"峰分离度不足({sep:.2f} dB)"
    return True, "双峰可分"


def estimate_threshold(
    vv_db: np.ndarray,
    valid: np.ndarray | None = None,
    *,
    t_default: float = -18.0,
    t_clamp: tuple[float, float] = (-23.0, -14.0),
    method: str = "ki",
    min_samples: int = 64,
    min_class_fraction: float = 0.05,
    min_separation_db: float = 2.0,
    bin_width: float = 0.5,
) -> ThresholdResult:
    """
    对有效像元估计 VV 阈值并夹逼。
    调用方应事先把建成区、陡坡像元从 valid 中去掉（不参与估计）。
    """
    arr = np.asarray(vv_db, dtype=np.float64)
    if valid is None:
        mask = np.isfinite(arr)
    else:
        mask = np.asarray(valid, dtype=bool) & np.isfinite(arr)
    values = arr[mask]
    n_valid = int(values.size)
    lo, hi = float(min(t_clamp)), float(max(t_clamp))

    def fallback(reason: str, t_auto: float | None = None) -> ThresholdResult:
        return ThresholdResult(
            T=float(t_default),
            T_auto=t_auto,
            T_default=float(t_default),
            clamp=(lo, hi),
            source="default",
            method=None,
            n_valid=n_valid,
            bimodal=False,
            reason=reason,
        )

    if n_valid < min_samples:
        return fallback(f"有效像元过少({n_valid}<{min_samples})")

    vmin = float(np.min(values))
    vmax = float(np.max(values))
    if vmax - vmin < 1e-6:
        return fallback("像元值几乎恒定，无法形成双峰")

    start = np.floor(vmin / bin_width) * bin_width
    stop = np.ceil(vmax / bin_width) * bin_width + bin_width
    edges = np.arange(start, stop + 1e-9, bin_width)
    if edges.size < 6:
        edges = np.linspace(vmin, vmax, 16)
    counts, centers = _histogram(values, edges)
    if counts.sum() <= 0 or (counts > 0).sum() < 4:
        return fallback("直方图有效箱过少")

    t_auto: float | None = None
    used_method: str | None = None
    try:
        if method == "otsu":
            t_auto, _ = otsu_threshold(counts, centers)
            used_method = "otsu"
        else:
            t_auto, _ = kittler_illingworth(counts, centers)
            used_method = "ki"
            # KI 失败退化到 Otsu
            if not np.isfinite(t_auto):
                t_auto, _ = otsu_threshold(counts, centers)
                used_method = "otsu"
    except ValueError as exc:
        return fallback(f"阈值估计失败: {exc}")

    ok, reason = is_bimodal(
        values,
        t_auto,
        min_samples=min_samples,
        min_class_fraction=min_class_fraction,
        min_separation_db=min_separation_db,
    )
    if not ok:
        return fallback(reason, t_auto=t_auto)

    clamped = min(max(t_auto, lo), hi)
    if clamped != t_auto and abs(clamped - t_auto) > 1e-9:
        source = "auto_clamped"
        reason = f"T_auto={t_auto:.3f} 已夹逼到 [{lo}, {hi}]"
    else:
        source = "auto"
        reason = "双峰自适应阈值"
    return ThresholdResult(
        T=float(clamped),
        T_auto=float(t_auto),
        T_default=float(t_default),
        clamp=(lo, hi),
        source=source,
        method=used_method,
        n_valid=n_valid,
        bimodal=True,
        reason=reason,
    )
