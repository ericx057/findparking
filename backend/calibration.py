"""Adaptive weight calibration: learns from prediction accuracy over time.

Runs nightly to compare each signal's predicted direction (value > 0.5 means
"available") against actual occupancy changes, then adjusts effective weight
multipliers within [0.25x, 2.0x] of base_weight.

Also detects cross-signal correlation to dampen double-counting.
"""

import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("findparking.calibration")

_LOOKBACK_DAYS = 7
_MIN_SAMPLES = 20
_MULTIPLIER_FLOOR = 0.25
_MULTIPLIER_CEILING = 2.0
_CORRELATION_THRESHOLD = 0.80


def calibrate_weights(conn: sqlite3.Connection) -> None:
    """Recompute effective_weight_multiplier for each signal from audit data."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Get distinct signals with enough samples
    signals = conn.execute(
        "SELECT signal_source, COUNT(*) as cnt "
        "FROM signal_audit_log WHERE timestamp >= ? "
        "GROUP BY signal_source HAVING cnt >= ?",
        (cutoff, _MIN_SAMPLES),
    ).fetchall()

    if not signals:
        logger.info("calibrate_weights: insufficient audit data, skipping")
        return

    signal_accuracies = {}

    for sig_row in signals:
        signal_name = sig_row["signal_source"]
        accuracy = _compute_directional_accuracy(conn, signal_name, cutoff)
        if accuracy is not None:
            signal_accuracies[signal_name] = accuracy

    if not signal_accuracies:
        logger.info("calibrate_weights: no computable accuracies")
        return

    # Compute multipliers
    multipliers = {}
    for signal_name, accuracy in signal_accuracies.items():
        # accuracy_multiplier = 0.5 + accuracy_ratio (range: 0.5 to 1.5)
        multiplier = 0.5 + accuracy
        multiplier = max(_MULTIPLIER_FLOOR, min(_MULTIPLIER_CEILING, multiplier))
        multipliers[signal_name] = multiplier

    # Cross-signal correlation dampening
    _apply_correlation_dampening(conn, cutoff, multipliers)

    # Store multipliers in signal_params
    for signal_name, multiplier in multipliers.items():
        conn.execute(
            "INSERT OR REPLACE INTO signal_params "
            "(signal_name, param_key, param_value, updated_at) "
            "VALUES (?, 'effective_weight_multiplier', ?, datetime('now'))",
            (signal_name, round(multiplier, 4)),
        )

    conn.commit()
    logger.info(
        "calibrate_weights: updated %d signal multipliers", len(multipliers)
    )


def _compute_directional_accuracy(
    conn: sqlite3.Connection, signal_name: str, cutoff: str,
) -> float | None:
    """Compute how often a signal correctly predicted availability direction.

    For each audit log entry, check if the signal's value (> 0.5 = available)
    matches the actual vacancy direction in the next occupancy snapshot.
    """
    rows = conn.execute(
        "SELECT a.lot_id, a.timestamp, a.raw_value "
        "FROM signal_audit_log a "
        "WHERE a.signal_source = ? AND a.timestamp >= ? "
        "ORDER BY a.lot_id, a.timestamp",
        (signal_name, cutoff),
    ).fetchall()

    if not rows:
        return None

    correct = 0
    total = 0

    for row in rows:
        lot_id = row["lot_id"]
        ts = row["timestamp"]
        predicted_available = row["raw_value"] > 0.5

        # Find next snapshot for this lot
        snap = conn.execute(
            "SELECT vacancy_ratio FROM occupancy_snapshots "
            "WHERE lot_id = ? AND timestamp > ? "
            "ORDER BY timestamp ASC LIMIT 1",
            (lot_id, ts),
        ).fetchone()

        if snap is None:
            continue

        actual_available = snap["vacancy_ratio"] > 0.3
        if predicted_available == actual_available:
            correct += 1
        total += 1

    if total < _MIN_SAMPLES:
        return None

    return correct / total


def _apply_correlation_dampening(
    conn: sqlite3.Connection, cutoff: str,
    multipliers: dict[str, float],
) -> None:
    """Reduce weight of correlated signals to avoid double-counting.

    When two signals have Pearson r > 0.80 over the trailing week,
    the lighter signal's multiplier is halved.
    """
    signal_names = list(multipliers.keys())
    if len(signal_names) < 2:
        return

    # Collect per-lot values for each signal
    signal_values: dict[str, dict[str, list[float]]] = {}
    for name in signal_names:
        rows = conn.execute(
            "SELECT lot_id, raw_value FROM signal_audit_log "
            "WHERE signal_source = ? AND timestamp >= ?",
            (name, cutoff),
        ).fetchall()
        by_lot: dict[str, list[float]] = {}
        for row in rows:
            by_lot.setdefault(row["lot_id"], []).append(row["raw_value"])
        signal_values[name] = by_lot

    # Pairwise correlation check
    for i in range(len(signal_names)):
        for j in range(i + 1, len(signal_names)):
            name_a = signal_names[i]
            name_b = signal_names[j]
            r = _pearson_r(signal_values.get(name_a, {}),
                           signal_values.get(name_b, {}))
            if r is not None and r > _CORRELATION_THRESHOLD:
                # Dampen the lighter (lower multiplier) signal
                if multipliers[name_a] <= multipliers[name_b]:
                    multipliers[name_a] *= 0.5
                    multipliers[name_a] = max(_MULTIPLIER_FLOOR, multipliers[name_a])
                else:
                    multipliers[name_b] *= 0.5
                    multipliers[name_b] = max(_MULTIPLIER_FLOOR, multipliers[name_b])
                logger.info(
                    "correlation_dampening: %s <-> %s r=%.3f",
                    name_a, name_b, r,
                )


def _pearson_r(
    values_a: dict[str, list[float]],
    values_b: dict[str, list[float]],
) -> float | None:
    """Compute Pearson correlation coefficient between two signals.

    Uses per-lot mean values for lots present in both signal datasets.
    """
    common_lots = set(values_a.keys()) & set(values_b.keys())
    if len(common_lots) < 10:
        return None

    xs = []
    ys = []
    for lot_id in common_lots:
        xs.append(sum(values_a[lot_id]) / len(values_a[lot_id]))
        ys.append(sum(values_b[lot_id]) / len(values_b[lot_id]))

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    cov = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)

    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return None

    return cov / denom
