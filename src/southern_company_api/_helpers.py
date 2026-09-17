"""Small shared helpers for reading Southern Company's JSON payloads.

The OCC ("Ascend") API returns camelCase where the retired
customerservice2api estate returned PascalCase, and it spreads the ids a usage
request needs across sibling arrays. These helpers keep both parser.py and
account.py tolerant of that without repeating the lookups.
"""

import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .company import COMPANY_MAP, Company

_LOGGER = logging.getLogger(__name__)


def first(data: Any, *names: str, default: Any = None) -> Any:
    """First present, non-null value among *names* (case-insensitive)."""
    if not isinstance(data, Mapping):
        return default
    lowered = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return default


def company_from(raw: Any, default: Company = Company.GPC) -> Company:
    """Map a company/division code -- numeric id or "GPC"-style name -- to Company.

    Returns *default* when the code is missing or not recognised, so callers
    decide their own fallback instead of unknown codes silently becoming GPC.
    """
    if isinstance(raw, bool) or raw in (None, ""):
        return default
    if isinstance(raw, int):
        return COMPANY_MAP.get(raw, default)
    if isinstance(raw, str):
        token = raw.strip()
        if token.isdigit():
            return COMPANY_MAP.get(int(token), default)
        for company in Company:
            if company.name.lower() == token.lower():
                return company
    return default


def deep_find(payload: Any, key: str, depth: int = 6) -> Any:
    """First value for *key* anywhere in a nested structure, breadth-first.

    The account summary splits the ids a usage request needs across sibling
    arrays -- ``serviceAgreements[]`` carries ``serviceAgreementId`` and
    ``premiseId`` while a top-level ``servicePoints[]`` carries
    ``servicePointId`` -- and the nesting varies by account type, so search
    instead of assuming a path.
    """
    frontier: List[Any] = [payload]
    for _ in range(depth):
        if not frontier:
            return None
        following: List[Any] = []
        for node in frontier:
            if isinstance(node, Mapping):
                value = first(node, key)
                if value not in (None, ""):
                    return value
                following.extend(node.values())
            elif isinstance(node, list):
                following.extend(node)
        frontier = following
    return None


def _series_matches(name: str, wanted: Tuple[str, ...]) -> bool:
    lowered = name.lower()
    if "projected" in lowered:
        # forecasts, not meter data
        return False
    return any(token in lowered for token in wanted)


def series_points(graph: Mapping[str, Any], *wanted: str) -> Dict[str, float]:
    """Collect ``{label: y}`` from every graph series matching one of *wanted*.

    Series names vary by granularity and company -- ``cost`` hourly,
    ``weekdayCost``/``weekendCost`` daily -- so they are matched by substring.
    Each granularity also ships ``*Delayed`` variants holding late-arriving
    reads for buckets that were empty at first publish. Those are read *after*
    the plain series and only fill labels still missing, so a real reading
    always wins no matter which key the response happens to list first.

    A delayed point with ``y == 0`` is not a reading: the hourly endpoint
    lists every bucket the meter has not reported yet in ``usageDelayed`` /
    ``costDelayed`` with a zero, while the daily endpoint keeps returning real
    totals for the same days. Taking those zeros as data writes 0 kWh hours
    that a consumer keyed on "already have a row for this hour" never
    revisits, so they are left out and the label stays missing.
    """
    series = graph.get("series") or {}
    if not isinstance(series, Mapping):
        return {}

    matching = [
        (str(name), payload)
        for name, payload in series.items()
        if _series_matches(str(name), wanted)
    ]
    # False sorts before True, and sorted() is stable: plain series keep their
    # response order and come first, delayed ones follow.
    matching.sort(key=lambda item: "delayed" in item[0].lower())
    if matching:
        _LOGGER.debug(
            "%s resolved from series %s", "/".join(wanted), [n for n, _ in matching]
        )

    points: Dict[str, float] = {}
    for name, payload in matching:
        delayed = "delayed" in name.lower()
        for point in (payload or {}).get("data") or []:
            label = point.get("name")
            value = point.get("y")
            if label is None or value is None:
                continue
            if delayed and not value:
                continue
            points.setdefault(label, value)
    return points


def graph_labels(graph: Mapping[str, Any]) -> List[str]:
    """The x-axis labels (ISO timestamps) of a usage graph payload."""
    labels = (graph.get("xAxis") or {}).get("labels")
    return list(labels) if labels else []


def unwrap(response: Any, what: str) -> Any:
    """Unwrap the ``{statusCode, status, message, data, modelErrors}`` envelope."""
    payload: Optional[Any] = first(response, "data", "Data")
    if payload is None:
        keys = (
            list(response.keys()) if isinstance(response, Mapping) else type(response)
        )
        raise KeyError(f"No data in {what} response (got {keys})")
    return payload
