"""Turn one messy NISR Excel sheet into a clean, tidy-ish DataFrame."""
import re
import unicodedata

import pandas as pd
from openpyxl import load_workbook

from pipeline.geo import DISTRICT_BY_NAME, PROVINCES, classify_geo, normalise_name

MISSING = {"", "-", "..", ".", "na", "n/a", "x", "*"}
STANDARD_NAMES = [
    (r"std_?error", "std_error"),
    (r"95.*lower", "ci_low"),
    (r"95.*upper", "ci_high"),
    (r"^cv(_|$)", "cv"),
    (r"design_effect", "design_effect"),
    (r"unweighted_count", "unweighted_count"),
    (r"^estimate$", "value"),
]

_workbooks = {}


def clean_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("Back to List of Tables", "")
    text = re.sub(r"\[\d+\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_number(value):
    """Return a float for numeric cells and numeric-looking strings, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if value != value else float(value)
    text = clean_text(value)
    if text.casefold() in MISSING:
        return None
    text = re.sub(r"\[\d+\]", "", text).replace(",", "").replace("%", "").replace(" ", "")
    try:
        return float(text)
    except ValueError:
        return None


def snake(text):
    text = clean_text(text).casefold().replace("%", " pct ").replace("…", "")
    text = re.sub(r"[^0-9a-z]+", "_", text).strip("_")
    return text


def _rows(path, sheet_name):
    key = str(path)
    if key not in _workbooks:
        _workbooks[key] = load_workbook(path, read_only=True, data_only=True)
    rows = []
    for row in _workbooks[key][sheet_name].iter_rows(values_only=True):
        rows.append([None if (isinstance(c, str) and not c.strip()) else c for c in row])
    return rows


def _first_text(row):
    for index, cell in enumerate(row):
        if isinstance(cell, str) and clean_text(cell):
            return index
    return None


def _column_names(header_rows, columns, short_names=False):
    """Flatten 1 to 3 header rows into snake_case names; carry merged group names forward."""
    filled = []
    for level, row in enumerate(header_rows):
        last = level == len(header_rows) - 1
        current, values = None, {}
        for j in columns:
            cell = clean_text(row[j]) if j < len(row) else ""
            if cell:
                current = cell
            values[j] = cell if (last or cell) else (current or "")
        filled.append(values)
    names = []
    for j in columns:
        parts = []
        for values in filled:
            part = snake(values[j])
            if short_names and len(part) > 25 and values is not filled[-1] and snake(filled[-1][j]):
                continue
            if part and (not parts or parts[-1] != part):
                parts.append(part)
        name = "_".join(parts) or f"col_{j}"
        for pattern, standard in STANDARD_NAMES:
            if re.search(pattern, name):
                name = standard
                break
        if name[0].isdigit():
            name = "v_" + name
        names.append(name[:63])
    seen = {}
    unique = []
    for name in names:
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        unique.append(name)
    return unique


def geo_fields(label):
    level = classify_geo(label)
    name = normalise_name(label)
    province = district = None
    area = "total"
    if level == "district":
        row = DISTRICT_BY_NAME[name]
        district, province = row["district"], row["province"]
    elif level == "province":
        province = PROVINCES[name]
    elif level == "urban_rural":
        area = "urban" if name.startswith("urban") else "rural"
    return level, province, district, area


def parse_sheet(path, sheet_name, first_col_name=None, short_names=False, rename=None):
    """Return (title, DataFrame) for a NISR table sheet."""
    rows = _rows(path, sheet_name)
    title_index = next(i for i, r in enumerate(rows) if any(clean_text(c) for c in r))
    title = next(clean_text(c) for c in rows[title_index] if clean_text(c))

    data_start = label_col = None
    for i in range(title_index + 1, len(rows)):
        position = _first_text(rows[i])
        if position is None:
            continue
        if any(clean_number(c) is not None for c in rows[i][position + 1:]):
            data_start, label_col = i, position
            break
    if data_start is None:
        raise ValueError(f"{sheet_name}: no data rows found")

    width = max(len(r) for r in rows[data_start:])
    columns = list(range(label_col + 1, width))
    header_rows = [r for r in rows[title_index + 1:data_start] if any(clean_text(c) for c in r[label_col + 1:])]
    names = _column_names(header_rows, columns, short_names)
    if first_col_name and names:
        names[0] = first_col_name
    names = [(rename or {}).get(n, n) for n in names]

    records, breakdown = [], None
    for row in rows[data_start:]:
        label = clean_text(row[label_col]) if label_col < len(row) else ""
        values = [clean_number(row[j]) if j < len(row) else None for j in columns]
        if not label:
            continue
        if all(v is None for v in values):
            breakdown = label
            continue
        level, province, district, area = geo_fields(label)
        record = {"label": label, "breakdown": breakdown, "geo_level": level,
                  "province": province, "district": district, "area": area}
        record.update(dict(zip(names, values)))
        records.append(record)

    frame = pd.DataFrame.from_records(records)
    value_cols = [n for n in names if n in frame.columns]
    empty = [c for c in value_cols if frame[c].isna().all()]
    frame = frame.drop(columns=empty)
    return title, frame


def parse_lfs_sheet(path, sheet_name):
    """LFS sheets are quarterly time series in blocks (one block per group). Return long format."""
    rows = _rows(path, sheet_name)
    title = clean_text(next(c for c in rows[0] if clean_text(c)))
    records, i = [], 1
    while i < len(rows):
        row = rows[i]
        if len(row) > 1 and clean_text(row[1]).startswith("Period"):
            group = clean_text(row[0]) or "Total"
            years, quarters = rows[i + 1], rows[i + 2]
            i += 3
            while i < len(rows) and not (len(rows[i]) > 1 and clean_text(rows[i][1]).startswith("Period")):
                label = clean_text(rows[i][0])
                if label and not label.startswith("Source"):
                    for j in range(1, len(rows[i])):
                        value = clean_number(rows[i][j])
                        year, quarter = clean_text(years[j]), clean_text(quarters[j])
                        if value is not None and year and quarter:
                            records.append({"indicator": label, "group": group, "year": int(year),
                                            "quarter": quarter, "period": f"{year}{quarter}", "value": value})
                i += 1
            continue
        i += 1
    frame = pd.DataFrame.from_records(records)
    frame.insert(0, "geo_level", "national")
    frame.insert(1, "province", None)
    frame.insert(2, "district", None)
    area = frame["group"].str.casefold().map({"urban": "urban", "rural": "rural"}).fillna("total")
    frame.insert(3, "area", area)
    return title, frame
