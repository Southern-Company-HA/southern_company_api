from southern_company_api._helpers import series_points


def _graph(**series):
    return {"series": {name: {"data": points} for name, points in series.items()}}


def test_series_points_plain_beats_delayed_regardless_of_key_order():
    graph = _graph(
        usageDelayed=[{"y": 9.9, "name": "h1"}],
        usage=[{"y": 1.5, "name": "h1"}],
    )
    assert series_points(graph, "usage") == {"h1": 1.5}


def test_series_points_delayed_fills_missing_label_when_it_has_a_value():
    graph = _graph(
        usage=[{"y": 1.5, "name": "h1"}],
        usageDelayed=[{"y": 2.25, "name": "h2"}],
    )
    assert series_points(graph, "usage") == {"h1": 1.5, "h2": 2.25}


def test_series_points_delayed_zero_is_not_a_reading():
    graph = _graph(
        usage=[{"y": 1.5, "name": "h1"}, {"y": 0, "name": "h2"}],
        usageDelayed=[{"y": 0, "name": "h3"}, {"y": 0, "name": "h4"}],
    )
    # a zero in the plain series is a real reading; a delayed zero is not
    assert series_points(graph, "usage") == {"h1": 1.5, "h2": 0}


def test_series_points_skips_projections_and_null_points():
    graph = _graph(
        usage=[{"y": None, "name": "h1"}, {"y": 3.0, "name": None}],
        projectedUsage=[{"y": 7.0, "name": "h1"}],
    )
    assert series_points(graph, "usage") == {}
