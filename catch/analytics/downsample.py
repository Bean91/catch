from __future__ import annotations

"""Largest-Triangle-Three-Buckets downsampling — pure functions, no I/O, per CLAUDE.md's
analytics-module convention. Used by GET /api/series (catch/api/routes_analytics.py) to keep
long chart histories under a bounded point count on a 1GB Pi."""


def lttb_indices(xs: list[float], ys: list[float], n: int) -> list[int]:
    """Returns the indices of the n points LTTB keeps, always including index 0 and the last
    index. If there are <= n points, or n < 3 (can't form first+last+at-least-one-middle),
    every index is returned unchanged."""
    length = len(xs)
    if length <= n or n < 3:
        return list(range(length))

    sampled = [0]
    # Points [1, length-2] are split into n-2 buckets; bucket 0 always starts at index 1.
    bucket_size = (length - 2) / (n - 2)
    a = 0
    for i in range(n - 2):
        bucket_start = int(i * bucket_size) + 1
        bucket_end = min(int((i + 1) * bucket_size) + 1, length - 1)
        if bucket_end <= bucket_start:
            bucket_end = bucket_start + 1

        next_start = bucket_end
        next_end = min(int((i + 2) * bucket_size) + 1, length)
        if next_end <= next_start:
            next_end = next_start + 1
        avg_x = sum(xs[j] for j in range(next_start, next_end)) / (next_end - next_start)
        avg_y = sum(ys[j] for j in range(next_start, next_end)) / (next_end - next_start)

        ax, ay = xs[a], ys[a]
        best_area = -1.0
        best_idx = bucket_start
        for j in range(bucket_start, bucket_end):
            area = abs((ax - avg_x) * (ys[j] - ay) - (ax - xs[j]) * (avg_y - ay))
            if area > best_area:
                best_area = area
                best_idx = j
        sampled.append(best_idx)
        a = best_idx

    sampled.append(length - 1)
    return sampled


def bucket_value_bounds(ys: list[float], indices: list[int]) -> list[tuple[float, float]]:
    """For each selected index, the (min, max) of `ys` over the half-open neighborhood toward
    its adjacent selected indices — an approximate "what did downsampling hide" band, without
    recomputing LTTB's own internal triangle-area buckets. One (y, y) pair per index when
    `indices` covers every point (nothing was actually downsampled)."""
    length = len(ys)
    out = []
    for pos, idx in enumerate(indices):
        if len(indices) == length or pos == 0 or pos == len(indices) - 1:
            out.append((ys[idx], ys[idx]))
            continue
        lo = (indices[pos - 1] + idx) // 2 + 1
        hi = (idx + indices[pos + 1]) // 2
        lo, hi = min(lo, idx), max(hi, idx)
        window = ys[lo : hi + 1] or [ys[idx]]
        out.append((min(window), max(window)))
    return out


def downsample_with_bounds(xs: list[float], ys: list[float], n: int) -> list[dict]:
    """Like lttb_indices, but also returns the min/max y seen in each kept point's source
    bucket (for an optional min/max band) alongside the representative x/y LTTB picked."""
    indices = lttb_indices(xs, ys, n)
    bounds = bucket_value_bounds(ys, indices)
    return [{"x": xs[idx], "y": ys[idx], "y_min": lo, "y_max": hi} for idx, (lo, hi) in zip(indices, bounds)]
