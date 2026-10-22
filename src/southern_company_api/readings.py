"""Publication timestamps without treating delayed zeros as completed reads."""

import dataclasses
import datetime as dt
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from ._helpers import graph_labels, series_points
from .exceptions import UsageDataFailure

UTC = dt.timezone.utc


def local_timestamp(label: str, timezone: dt.tzinfo) -> dt.datetime:
    value = dt.datetime.fromisoformat(label.replace("Z", "+00:00"))
    if value.tzinfo is not None:
        return value.astimezone(timezone)
    value = value.replace(tzinfo=timezone)
    if value.astimezone(UTC).astimezone(timezone).replace(tzinfo=None) != value.replace(
        tzinfo=None
    ):
        raise UsageDataFailure("Usage label falls in a nonexistent local hour")
    return value


def ambiguous(value: dt.datetime) -> bool:
    return value.replace(fold=0).utcoffset() != value.replace(fold=1).utcoffset()


def label_is_ambiguous(label: str, value: dt.datetime) -> bool:
    # Explicit UTC/offset labels resolve the autumn fold without guessing.
    return dt.datetime.fromisoformat(
        label.replace("Z", "+00:00")
    ).tzinfo is None and ambiguous(value)


def actual_points(graph: Mapping[str, Any], series: str) -> dict[str, float]:
    # The portal calls *Delayed series "Estimated Reading", including nonzero
    # estimates. They must never advance a completed-reading watermark.
    actual = {
        key: body
        for key, body in (graph.get("series") or {}).items()
        if "delayed" not in key.lower()
    }
    return series_points({"series": actual}, series)


@dataclasses.dataclass(frozen=True)
class ReadingStatus:
    granularity: str
    timezone: str
    latest_usage: Optional[dt.datetime]
    latest_cost: Optional[dt.datetime]
    # Label of the latest closed interval having BOTH usage and cost.
    # This does not assert that all preceding intervals are present.
    latest_complete_reading: Optional[dt.datetime]
    latest_complete_day: Optional[dt.date]
    ambiguous_labels: tuple[str, ...]


def reading_status(
    graph: Mapping[str, Any],
    granularity: str,
    timezone: ZoneInfo,
    now: Optional[dt.datetime] = None,
) -> ReadingStatus:
    if granularity not in ("hourly", "daily"):
        raise ValueError("Expected hourly or daily granularity")
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must have a timezone")
    usage = actual_points(graph, "usage")
    cost = actual_points(graph, "cost")
    labels = graph_labels(graph)
    times = {label: local_timestamp(label, timezone) for label in labels}
    ambiguous_labels = tuple(
        label for label, value in times.items() if label_is_ambiguous(label, value)
    )

    def closed(label: str) -> bool:
        value = times[label]
        if label in ambiguous_labels:
            return False
        if granularity == "daily":
            return value.date() < now.astimezone(timezone).date()
        return value.astimezone(UTC) + dt.timedelta(hours=1) <= now.astimezone(UTC)

    def latest(points: Mapping[str, float]) -> Optional[dt.datetime]:
        values = [times[label] for label in points if label in times and closed(label)]
        return max(values, key=lambda v: v.astimezone(UTC)) if values else None

    complete = {label: usage[label] for label in usage.keys() & cost.keys()}
    days = []
    for day in sorted({v.date() for v in times.values()}):
        if day >= now.astimezone(timezone).date():
            continue
        start = dt.datetime.combine(day, dt.time(), timezone)
        end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), timezone)
        expected = {start.astimezone(UTC)}
        if granularity == "hourly":
            expected = set()
            cursor = start.astimezone(UTC)
            while cursor < end.astimezone(UTC):
                expected.add(cursor)
                cursor += dt.timedelta(hours=1)
        actual = {
            times[label].astimezone(UTC)
            for label in complete
            if label in times and times[label].date() == day and closed(label)
        }
        if actual == expected:
            days.append(day)
    return ReadingStatus(
        granularity,
        timezone.key,
        latest(usage),
        latest(cost),
        latest(complete),
        max(days) if days else None,
        ambiguous_labels,
    )
