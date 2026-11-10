"""Deterministic BRNS opening-hours calculations."""

from datetime import datetime, timedelta, timezone


class OpeningHoursService:
    """Normalize and evaluate saved or live weekly opening periods."""

    SINGAPORE = timezone(timedelta(hours=8))
    DAYS = (
        "sunday", "monday", "tuesday", "wednesday", "thursday",
        "friday", "saturday",
    )
    WEEK_MINUTES = 7 * 24 * 60

    @staticmethod
    def _minute(point):
        if not isinstance(point, dict):
            return None
        day = point.get("day")
        hour = point.get("hour", 0)
        minute = point.get("minute", 0)
        if (type(day) is not int or not 0 <= day < 7
                or type(hour) is not int or not 0 <= hour < 24
                or type(minute) is not int or not 0 <= minute < 60):
            return None
        return day * 1440 + hour * 60 + minute

    def _intervals(self, hours):
        if not isinstance(hours, dict):
            return []
        intervals = []
        for period in hours.get("periods") or []:
            if not isinstance(period, dict):
                continue
            start = self._minute(period.get("open"))
            if start is None:
                continue
            if not period.get("close"):
                return [(0, self.WEEK_MINUTES)]
            end = self._minute(period["close"])
            if end is None:
                continue
            if end <= start:
                end += self.WEEK_MINUTES
            intervals.append((start, end))
        return intervals

    def _local_now(self, now=None):
        return (
            now.astimezone(self.SINGAPORE)
            if now is not None else datetime.now(self.SINGAPORE)
        )

    @staticmethod
    def _today_index(now):
        return (now.weekday() + 1) % 7

    @staticmethod
    def _fmt(minute):
        return f"{minute // 60:02d}:{minute % 60:02d}"

    def open_now_from_weekly(self, hours, now=None):
        if not isinstance(hours, dict):
            return False
        now = self._local_now(now)
        periods = hours.get(self.DAYS[self._today_index(now)])
        if not isinstance(periods, list):
            return False
        if len(periods) == 2 and all(
                isinstance(part, str) for part in periods):
            periods = [periods]
        minute = now.hour * 60 + now.minute
        for period in periods:
            if (not isinstance(period, list) or len(period) != 2
                    or any(not isinstance(part, str) or len(part) != 4
                           or not part.isdigit() for part in period)):
                continue
            start = int(period[0][:2]) * 60 + int(period[0][2:])
            end = int(period[1][:2]) * 60 + int(period[1][2:])
            if start <= minute < end or (end == 1439 and minute == 1439):
                return True
        return False

    def today_hours_from_weekly(self, hours, now=None):
        if not isinstance(hours, dict):
            return "Hours unavailable"
        periods = hours.get(
            self.DAYS[self._today_index(self._local_now(now))])
        if periods is None:
            return "Hours unavailable"
        if not periods:
            return "Closed today"
        if len(periods) == 2 and all(
                isinstance(part, str) for part in periods):
            periods = [periods]
        if periods == [["0000", "2359"]]:
            return "Open 24 hours"
        return ", ".join(
            f"{pair[0][:2]}:{pair[0][2:]}–{pair[1][:2]}:{pair[1][2:]}"
            for pair in periods
            if isinstance(pair, list) and len(pair) == 2
            and all(isinstance(part, str) and len(part) == 4
                    for part in pair)
        ) or "Hours unavailable"

    def weekly_opening_hours(self, hours):
        if not isinstance(hours, dict) or "periods" not in hours:
            return None
        week = {}
        for day_name in (*self.DAYS[1:], self.DAYS[0]):
            day_index = self.DAYS.index(day_name)
            day_start = day_index * 1440
            segments = set()
            for start, end in self._intervals(hours):
                for shift in (-self.WEEK_MINUTES, 0, self.WEEK_MINUTES):
                    left = max(day_start, start + shift)
                    right = min(day_start + 1440, end + shift)
                    if left < right:
                        local_start = left - day_start
                        local_end = right - day_start
                        segments.add((
                            f"{local_start // 60:02d}"
                            f"{local_start % 60:02d}",
                            "2359" if local_end == 1440 else
                            f"{local_end // 60:02d}{local_end % 60:02d}",
                        ))
            intervals = [list(pair) for pair in sorted(segments)]
            week[day_name] = (
                intervals[0] if len(intervals) == 1 else intervals)
        return week

    def today_hours(self, hours, now=None):
        now = self._local_now(now)
        day_start = self._today_index(now) * 1440
        segments = []
        for start, end in self._intervals(hours):
            for shift in (-self.WEEK_MINUTES, 0, self.WEEK_MINUTES):
                left = max(day_start, start + shift)
                right = min(day_start + 1440, end + shift)
                if left < right:
                    segments.append((left - day_start, right - day_start))
        segments = sorted(set(segments))
        if segments == [(0, 1440)]:
            return "Open 24 hours"
        if not segments:
            if isinstance(hours, dict) and hours.get("periods") == []:
                return "Closed today"
            return "Hours unavailable"
        return ", ".join(
            f"{self._fmt(start)}–"
            f"{self._fmt(end) if end < 1440 else '24:00'}"
            for start, end in segments)

    def open_now(self, hours, now=None):
        if not isinstance(hours, dict):
            return None
        if type(hours.get("openNow")) is bool:
            return hours["openNow"]
        intervals = self._intervals(hours)
        if not intervals:
            return False if "periods" in hours else None
        now = self._local_now(now)
        minute = self._today_index(now) * 1440 + now.hour * 60 + now.minute
        return any(
            start <= minute < end
            or start <= minute + self.WEEK_MINUTES < end
            for start, end in intervals
        )
