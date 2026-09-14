"""Reading and writing times such as 45, 1:30, 1:05:00, 5m or 1m30s."""
import re

_NUMBER = r"\d+(?:\.\d*)?"
_UNITS = re.compile(r"^(?:(?P<h>%s)\s*h)?\s*(?:(?P<m>%s)\s*m(?:in)?)?\s*(?:(?P<s>%s)\s*s?(?:ec)?)?$"
                    % (_NUMBER, _NUMBER, _NUMBER))


def parse_time(text):
    """Returns seconds, or None for an empty string. Raises ValueError if it isn't a time.

    A plain number means seconds ("90"). Colons mean minutes:seconds or hours:minutes:seconds
    ("1:30", "1:05:00"); "5:" counts as 5:00, which is handy while typing. Units work too:
    "5m", "1m30s", "1h".
    """
    text = (text or "").strip().lower()
    if not text:
        return None
    if ":" in text:
        parts = text.split(":")
        if len(parts) > 3 or not parts[0]:
            raise ValueError(text)
        total = 0.0
        for part in parts:
            part = part.strip()
            if part and not re.fullmatch(_NUMBER, part):
                raise ValueError(text)
            total = total * 60 + float(part or 0)
        return total
    match = _UNITS.match(text)
    if not match or not any(match.groupdict().values()):
        raise ValueError(text)
    hours, minutes, seconds = (float(match.group(k) or 0) for k in "hms")
    return hours * 3600 + minutes * 60 + seconds


def format_time(seconds):
    """1:05 or 1:02:03."""
    seconds = int(round(seconds or 0))
    if seconds >= 3600:
        return "%d:%02d:%02d" % (seconds // 3600, seconds // 60 % 60, seconds % 60)
    return "%d:%02d" % (seconds // 60, seconds % 60)
