"""The brew record as long-term statistics, so charts can draw it.

Home Assistant's statistics chart draws hourly sums. This turns every brew in
the record into those sums — brews by the xBloom, brews by hand, coffee used
and water brewed — and hands them to the recorder as external statistics.

Rebuilt whole after each change rather than appended to: the record is the
truth, and a brew corrected or removed there must leave the chart as well.
Built from the record, the charts include every brew recorded before this
existed, not only the ones since.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .lab import XBLOOM_BREWER, CoffeeLab
from .models import Brew
from .stats import made_coffee, moment

_LOGGER = logging.getLogger(__name__)

SOURCE = "xbloom"
# Changes arrive in bursts — a brew is counted, then its bag re-read — so the
# rebuild waits for them to settle.
SETTLE_S = 30


@dataclass(frozen=True)
class Series:
    key: str
    name: str
    unit: str | None
    unit_class: str | None
    value: Callable[[Brew], float]


SERIES = (
    Series("brews_xbloom", "xBloom brews", None, None,
           lambda b: 1.0 if made_coffee(b) and b.brewer == XBLOOM_BREWER else 0.0),
    Series("brews_manual", "Manual brews", None, None,
           lambda b: 1.0 if made_coffee(b) and b.brewer != XBLOOM_BREWER else 0.0),
    # Grams count every brew's coffee, a brew stopped after grinding included:
    # the coffee was used, as in the period totals.
    Series("coffee_used", "Coffee used", "g", "mass", lambda b: float(b.dose_g or 0)),
    Series("water_brewed", "Water brewed", "mL", "volume", lambda b: float(b.water_ml or 0)),
)


def statistic_id(series: Series) -> str:
    return f"{SOURCE}:{series.key}"


def hourly(records: list[Brew], series: Series, zone: tzinfo) -> list[tuple[datetime, float]]:
    """(hour, running total) for each hour the series changed, oldest first.

    A statistics chart reads the change between hours, so only hours where
    something happened need a point; the total carries across the rest.
    """
    per_hour: dict[datetime, float] = {}
    for record in records:
        when = moment(record.brewed_at or record.recorded_at, zone)
        amount = series.value(record)
        if when is None or not amount:
            continue
        hour = when.replace(minute=0, second=0, microsecond=0)
        per_hour[hour] = per_hour.get(hour, 0.0) + amount
    points: list[tuple[datetime, float]] = []
    total = 0.0
    for hour in sorted(per_hour):
        total += per_hour[hour]
        points.append((hour, total))
    return points


def first_hour(records: list[Brew], zone: tzinfo) -> datetime | None:
    """The hour of the earliest brew in the record."""
    times = [m for r in records if (m := moment(r.brewed_at or r.recorded_at, zone)) is not None]
    return min(times).replace(minute=0, second=0, microsecond=0) if times else None


async def async_publish(hass: HomeAssistant, lab: CoffeeLab) -> None:
    """Replace the charts' statistics with what the record holds now."""
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.models import StatisticMeanType
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    records = await lab.store.async_list_brews()
    zone = dt_util.get_default_time_zone()
    recorder = get_instance(hass)
    # Cleared first, so an hour that no longer has a brew loses its point.
    recorder.async_clear_statistics([statistic_id(s) for s in SERIES])
    # A series with nothing to count still gets a zero, so its chart is an
    # empty chart rather than a message that no statistics exist.
    first = first_hour(records, zone) or dt_util.now().replace(minute=0, second=0, microsecond=0)
    for series in SERIES:
        points = hourly(records, series, zone) or [(first, 0.0)]
        async_add_external_statistics(
            hass,
            {
                "mean_type": StatisticMeanType.NONE,
                "has_sum": True,
                "name": series.name,
                "source": SOURCE,
                "statistic_id": statistic_id(series),
                "unit_class": series.unit_class,
                "unit_of_measurement": series.unit,
            },
            [{"start": hour, "state": total, "sum": total} for hour, total in points],
        )


class ChartFeed:
    """Rebuilds the statistics once changes settle; one rebuild at a time."""

    def __init__(self, hass: HomeAssistant, lab: CoffeeLab) -> None:
        self.hass = hass
        self.lab = lab
        self._pending: Callable[[], None] | None = None

    @callback
    def schedule(self, *_: object) -> None:
        if self._pending is not None:
            self._pending()
        self._pending = async_call_later(self.hass, SETTLE_S, self._run)

    async def _run(self, _now: datetime) -> None:
        self._pending = None
        try:
            await async_publish(self.hass, self.lab)
        except Exception:  # noqa: BLE001 — a failed chart must not stop counting
            _LOGGER.exception("Could not rebuild the brew charts")

    @callback
    def cancel(self) -> None:
        if self._pending is not None:
            self._pending()
            self._pending = None
