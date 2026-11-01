from catch.analytics.downsample import downsample_with_bounds, lttb_indices


def test_lttb_returns_all_indices_when_n_covers_length():
    xs = list(range(10))
    ys = [float(i) for i in xs]
    assert lttb_indices(xs, ys, 10) == list(range(10))
    assert lttb_indices(xs, ys, 50) == list(range(10))


def test_lttb_returns_all_indices_when_n_below_three():
    xs = list(range(10))
    ys = [float(i) for i in xs]
    assert lttb_indices(xs, ys, 2) == list(range(10))


def test_lttb_keeps_first_and_last():
    xs = [float(i) for i in range(500)]
    ys = [float((i * 37) % 97) for i in range(500)]
    indices = lttb_indices(xs, ys, 50)
    assert indices[0] == 0
    assert indices[-1] == 499


def test_lttb_returns_exactly_n_points():
    xs = [float(i) for i in range(500)]
    ys = [float((i * 37) % 97) for i in range(500)]
    for n in (3, 10, 50, 200):
        assert len(lttb_indices(xs, ys, n)) == n


def test_lttb_indices_are_strictly_increasing():
    xs = [float(i) for i in range(1000)]
    ys = [float((i * 13) % 211) for i in range(1000)]
    indices = lttb_indices(xs, ys, 100)
    assert indices == sorted(set(indices))
    assert len(indices) == len(set(indices))


def test_lttb_preserves_a_sharp_spike_better_than_uniform_striding():
    # A single spike in otherwise-flat data should survive downsampling — LTTB picks the
    # point with the largest triangle area, which a spike maximizes.
    xs = [float(i) for i in range(300)]
    ys = [0.0] * 300
    ys[150] = 100.0
    indices = lttb_indices(xs, ys, 30)
    assert 150 in indices


def test_downsample_with_bounds_passthrough_when_short():
    xs = [1.0, 2.0, 3.0]
    ys = [10.0, 20.0, 15.0]
    out = downsample_with_bounds(xs, ys, 10)
    assert out == [
        {"x": 1.0, "y": 10.0, "y_min": 10.0, "y_max": 10.0},
        {"x": 2.0, "y": 20.0, "y_min": 20.0, "y_max": 20.0},
        {"x": 3.0, "y": 15.0, "y_min": 15.0, "y_max": 15.0},
    ]


def test_downsample_with_bounds_returns_n_points_and_keeps_extremes():
    xs = [float(i) for i in range(400)]
    ys = [float((i * 29) % 83) for i in range(400)]
    out = downsample_with_bounds(xs, ys, 40)
    assert len(out) == 40
    assert out[0]["x"] == 0.0
    assert out[-1]["x"] == 399.0
    for point in out:
        assert point["y_min"] <= point["y"] <= point["y_max"]
