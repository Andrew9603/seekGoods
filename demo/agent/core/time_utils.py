from __future__ import annotations

from datetime import datetime, timedelta

EPOCH = datetime(2026, 3, 1, 0, 0, 0)
FMT = "%Y-%m-%d %H:%M:%S"


def wall_time_to_minute(text: str) -> int:
    return int((datetime.strptime(text.strip(), FMT) - EPOCH).total_seconds() // 60)


def minute_to_datetime(minute: int) -> datetime:
    return EPOCH + timedelta(minutes=int(minute))


def day_index(minute: int) -> int:
    return int(minute) // 1440


def minute_of_day(minute: int) -> int:
    return int(minute) % 1440
