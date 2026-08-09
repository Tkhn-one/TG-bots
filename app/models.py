from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Watch:
    id: int
    user_id: int
    name: str
    url: str
    interval_minutes: int
    is_active: bool
    last_checked_at: datetime | None


@dataclass(frozen=True)
class Listing:
    external_id: str
    title: str
    url: str
    price: str | None = None
    location: str | None = None
    published_at: str | None = None
