"""Check that every number in an answer comes from the query results (or a simple derivation of them)."""
import re
from itertools import permutations

SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9}
IGNORE_PATTERNS = [
    r"\b(?:tables?|annex)\s+[a-z]?\.?\d+(?:\.\d+)*\b",   # Table 28, Table A9.23, Table B.07
    r"\b[a-z]{1,2}\.?\d+\.\d+\b",                         # A9.23, B.07, A.05
    r"\b[a-z]+\d+[a-z]*\b",                               # EICV7, PHC5, LU1, Q2, 2026Q2-style tokens
    r"\b(?:19|20)\d{2}\s*/\s*\d{2,4}\b",                  # 2023/24
    r"\b95\s*%\s*(?:confidence|ci)\b",                    # 95% confidence interval
    r"icyizere\s+(?:cya|ya|cy'|y')?\s*95\s*%",               # Kinyarwanda: intera y'icyizere ya 95%
    r"confiance\s+(?:de|à|a)\s+95\s*%",                      # French: intervalle de confiance à 95 %
    r"\bq[1-4]\b",
]
NUMBER = re.compile(
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<pct>\s*(?:%|percent\b|per cent\b))?"
    r"(?:\s*(?P<scale>thousand|million|billion|bn|k|m)\b)?",
    re.I)


def extract_numbers(text):
    """Return a list of {text, value, decimals, scale} for numbers that need checking."""
    cleaned = text or ""
    for pattern in IGNORE_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.I)
    found = []
    for match in NUMBER.finditer(cleaned):
        raw = match.group("num")
        digits = raw.replace(",", "")
        value = float(digits)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = SCALE[match.group("scale").casefold()] if match.group("scale") else 1
        is_year = scale == 1 and not match.group("pct") and decimals == 0 and "," not in raw and 1990 <= value <= 2035
        found.append({"text": match.group(0).strip(), "value": value * scale, "decimals": decimals,
                      "scale": scale, "is_year": is_year})
    return found


def numbers_in_strings(values):
    out = set()
    for value in values:
        if isinstance(value, str):
            out.update(float(n) for n in re.findall(r"\d+(?:\.\d+)?", value))
    return out


def collect_values(results):
    """All numeric cells from the session's query results, plus row counts and numbers inside labels."""
    numbers, context = [], set()
    for result in results or []:
        if not result or "rows" not in result:
            continue
        context.update(range(0, result.get("row_count", len(result["rows"])) + 1))
        context.update(numbers_in_strings(result.get("columns", [])))
        for row in result["rows"]:
            for cell in row:
                if isinstance(cell, bool):
                    continue
                if isinstance(cell, (int, float)):
                    numbers.append(float(cell))
                elif isinstance(cell, str):
                    context.update(numbers_in_strings([cell]))
    return numbers, context


def _close(candidate, number, slack=0.0):
    tolerance = 0.5 * 10 ** (-number["decimals"]) * number["scale"] + slack + 1e-9
    target = number["value"]
    if abs(abs(candidate) - target) <= tolerance:
        return True
    return target >= 1000 and abs(abs(candidate) - target) <= 0.005 * target


def _source_of(number, results):
    """Index of the first query result that contains this number (for tagging it with its NISR table)."""
    for index, result in enumerate(results or []):
        for row in result.get("rows", []):
            if any(isinstance(c, (int, float)) and not isinstance(c, bool) and _close(float(c), number) for c in row):
                return index
    return None


def verify(answer_text, results, extra_context=()):
    """Return {status, checked, unmatched, tags}. status is 'verified' when every number is supported.

    tags lists each checked number in answer order: {text, match: direct|derived|context|unmatched, result}.
    """
    numbers = extract_numbers(answer_text)
    values, context = collect_values(results)
    context.update(extra_context)
    direct_hits, unmatched, tags = [], [], {}
    pending = []
    for position, number in enumerate(numbers):
        if number["is_year"]:
            continue  # years and survey periods are context, not statistics
        if any(_close(v, number) for v in values):
            tags[position] = {"text": number["text"], "match": "direct", "result": _source_of(number, results)}
            direct_hits.extend(v for v in values if _close(v, number))
        elif number["decimals"] == 0 and number["scale"] == 1 and number["value"] in context:
            tags[position] = {"text": number["text"], "match": "context", "result": None}
        elif number["is_year"]:
            continue
        else:
            pending.append((position, number))
    pool = list(dict.fromkeys(direct_hits))
    if len(values) <= 300:
        pool = list(dict.fromkeys(pool + values))
    for position, number in pending:
        derived = any(_close(a - b, number, 0.011) or (b and _close(a / b, number, 0.011)) for a, b in permutations(pool, 2))
        if derived:
            tags[position] = {"text": number["text"], "match": "derived", "result": None}
        else:
            tags[position] = {"text": number["text"], "match": "unmatched", "result": None}
            unmatched.append(number["text"])
    ordered = [tags[k] for k in sorted(tags)]
    return {"status": "verified" if not unmatched else "unverified",
            "checked": sum(t["match"] != "unmatched" for t in ordered), "unmatched": unmatched, "tags": ordered}
