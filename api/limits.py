"""Public-demo protection: per-IP request rate, per-IP and global daily spend caps.

In-memory, so it holds for the single backend instance the demo runs on. Spend is
recorded after each turn from Claude's reported usage; a request is refused once
its IP or the whole service has spent the day's budget.
"""
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Limits:
    def __init__(self, per_minute: int | None = None, ip_daily_usd: float | None = None,
                 daily_usd: float | None = None, clock=time.time):
        self.per_minute = per_minute if per_minute is not None else int(_env_float("CHAT_PER_MINUTE", 6))
        self.ip_daily_usd = ip_daily_usd if ip_daily_usd is not None else _env_float("IP_DAILY_BUDGET_USD", 0.75)
        self.daily_usd = daily_usd if daily_usd is not None else _env_float("DAILY_BUDGET_USD", 8.0)
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = defaultdict(deque)
        self._day = None
        self._spend: dict[str, float] = defaultdict(float)
        self._total = 0.0

    def _roll_day(self) -> None:
        day = datetime.fromtimestamp(self.clock(), tz=timezone.utc).date()
        if day != self._day:
            self._day, self._spend, self._total = day, defaultdict(float), 0.0

    def check(self, ip: str) -> str | None:
        """None if the request may run, else a message saying why not."""
        with self._lock:
            self._roll_day()
            now, hits = self.clock(), self._hits[ip]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return f"Too many requests: the demo allows {self.per_minute} questions a minute. Try again shortly."
            if self._total >= self.daily_usd:
                return "The demo has used today's budget. It resets at midnight UTC."
            if self._spend[ip] >= self.ip_daily_usd:
                return "You've used today's demo budget. It resets at midnight UTC."
            hits.append(now)
            return None

    def record(self, ip: str, usd: float) -> None:
        with self._lock:
            self._roll_day()
            self._spend[ip] += usd
            self._total += usd

    def status(self) -> dict:
        with self._lock:
            self._roll_day()
            return {"spent_today_usd": round(self._total, 4), "daily_budget_usd": self.daily_usd,
                    "ip_daily_budget_usd": self.ip_daily_usd, "per_minute": self.per_minute}


def client_ip(headers, fallback: str | None) -> str:
    fwd = headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (fallback or "unknown")
