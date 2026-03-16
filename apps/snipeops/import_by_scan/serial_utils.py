import re

_CTRL_CHARS = re.compile(r"[\x00-\x1F\x7F]")  # removes CR/LF/TAB etc.

def normalize_serial(value: str) -> str:
    if value is None:
        return ""
    s = str(value)
    s = _CTRL_CHARS.sub("", s)
    s = s.strip().replace(" ", "").upper()
    return s

def serial_candidates(raw: str) -> list[str]:
    """
    Try the scanned serial as-is first, then try dropping 1 char from
    the left or right to handle scanners that inject a stray char.
    """
    base = normalize_serial(raw)
    if not base:
        return []

    candidates = [base]
    if len(base) >= 2:
        candidates.append(base[1:])   # drop first char
        candidates.append(base[:-1])  # drop last char

    # De-dupe while preserving order
    out, seen = [], set()
    for c in candidates:
        if c and c not in seen:
            out.append(c)
            seen.add(c)
    return out