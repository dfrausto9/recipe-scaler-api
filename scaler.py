"""Scale recipes and convert units, with kitchen-friendly output.

Builds on ingredient_parser.py (shared with the Ingredient Parser API).
Pure Python, no dependencies.

    >>> scale_lines(["1 1/2 cups flour"], factor=2)[0]["text"]
    '3 cups flour'
"""

import re
from fractions import Fraction

from ingredient_parser import parse_ingredient

# --- Units -------------------------------------------------------------------
# Every volume is stored in milliliters and every weight in grams.
VOLUME_ML = {
    "teaspoon": 4.92892, "tablespoon": 14.7868, "fluid ounce": 29.5735,
    "cup": 236.588, "pint": 473.176, "quart": 946.353, "gallon": 3785.41,
    "milliliter": 1.0, "liter": 1000.0,
}
WEIGHT_G = {
    "ounce": 28.3495, "pound": 453.592,
    "milligram": 0.001, "gram": 1.0, "kilogram": 1000.0,
}
METRIC_UNITS = {"milliliter", "liter", "milligram", "gram", "kilogram"}

# Short names developers can send to /convert-unit, mapped to our unit names.
UNIT_ALIASES = {
    "tsp": "teaspoon", "teaspoons": "teaspoon",
    "tbsp": "tablespoon", "tablespoons": "tablespoon",
    "fl oz": "fluid ounce", "floz": "fluid ounce", "fluid ounces": "fluid ounce",
    "cups": "cup", "c": "cup", "pints": "pint", "pt": "pint",
    "quarts": "quart", "qt": "quart", "gallons": "gallon", "gal": "gallon",
    "ml": "milliliter", "milliliters": "milliliter", "millilitre": "milliliter",
    "l": "liter", "liters": "liter", "litre": "liter", "litres": "liter",
    "oz": "ounce", "ounces": "ounce", "lb": "pound", "lbs": "pound", "pounds": "pound",
    "mg": "milligram", "g": "gram", "grams": "gram", "kg": "kilogram", "kilograms": "kilogram",
}

PLURALS = {
    "teaspoon": "teaspoons", "tablespoon": "tablespoons", "fluid ounce": "fluid ounces",
    "cup": "cups", "pint": "pints", "quart": "quarts", "gallon": "gallons",
    "ounce": "ounces", "pound": "pounds", "pinch": "pinches", "dash": "dashes",
    "clove": "cloves", "can": "cans", "jar": "jars", "package": "packages",
    "bag": "bags", "box": "boxes", "bottle": "bottles", "stick": "sticks",
    "slice": "slices", "piece": "pieces", "sprig": "sprigs", "bunch": "bunches",
    "head": "heads", "stalk": "stalks", "handful": "handfuls", "drop": "drops",
}
SHORT = {"milliliter": "ml", "liter": "L", "milligram": "mg", "gram": "g", "kilogram": "kg"}

# Fractions people actually measure with.
NICE_FRACTIONS = [Fraction(n, d) for n, d in
                  [(1, 8), (1, 4), (1, 3), (3, 8), (1, 2), (5, 8), (2, 3), (3, 4), (7, 8)]]
FRACTION_TOLERANCE = 0.03  # within 3% of the exact amount counts as a clean measurement


def canonical_unit(name):
    """Turn 'tbsp', 'Tablespoons' or 'g' into our unit name, or None."""
    if not isinstance(name, str):
        return None
    key = name.strip().lower().rstrip(".")
    if key in VOLUME_ML or key in WEIGHT_G:
        return key
    return UNIT_ALIASES.get(key)


def unit_kind(unit):
    if unit in VOLUME_ML:
        return "volume"
    if unit in WEIGHT_G:
        return "weight"
    return None


# --- Number formatting --------------------------------------------------------

def _nearest_fraction(x):
    """Return (whole, Fraction or None, relative_error) for the closest kitchen amount."""
    whole = int(x)
    rem = x - whole
    best = (whole, None, abs(rem))
    for f in NICE_FRACTIONS:
        if abs(rem - float(f)) < best[2]:
            best = (whole, f, abs(rem - float(f)))
    if abs(rem - 1) < best[2]:
        best = (whole + 1, None, abs(rem - 1))
    rel = best[2] / x if x else 0
    return best[0], best[1], rel


def format_us(x):
    """Round to a kitchen measurement. 2.5 -> '2 1/2', 0.333 -> '1/3', 13.4 -> '13 1/2'.

    Returns (text, rounded_value, is_clean). is_clean is False when rounding moved
    the amount more than 3%, so callers can flag it as approximate.
    """
    if x is None:
        return None, None, True
    if x >= 10:  # big amounts: halves are plenty precise
        value = round(x * 2) / 2
        whole, half = int(value), value - int(value)
        text = f"{whole} 1/2" if half else str(whole)
        return text, value, abs(value - x) / x <= FRACTION_TOLERANCE
    whole, frac, rel = _nearest_fraction(x)
    if not whole and not frac:  # tiny amount below 1/16
        return None, 0, False
    value = whole + (float(frac) if frac else 0)
    if frac and whole:
        text = f"{whole} {frac.numerator}/{frac.denominator}"
    elif frac:
        text = f"{frac.numerator}/{frac.denominator}"
    else:
        text = str(whole)
    return text, value, rel <= FRACTION_TOLERANCE


def format_metric(x):
    """Round metric amounts the way cooks write them: 3.7 g, 45 g, 250 g, 1.25 kg."""
    if x is None:
        return None
    if x >= 100:
        x = round(x / 5) * 5
    elif x >= 10:
        x = round(x)
    elif x >= 1:
        x = round(x * 2) / 2
    else:
        x = round(x, 2)
    return f"{x:g}"


def _number(x):
    x = round(x, 3)
    return int(x) if x == int(x) else x


# --- Picking the best unit ----------------------------------------------------

# Larger units are tried first; each needs at least this much to be used.
US_VOLUME_LADDER = [("cup", 0.25), ("tablespoon", 1), ("teaspoon", 0)]
US_WEIGHT_LADDER = [("pound", 1), ("ounce", 0)]
PICK_TOLERANCE = 0.06
# "2 heaping tablespoons" means a heaping spoonful; don't turn it into a heaping cup.
LOOSE_SIZES = {"heaping", "scant", "level", "generous"}
# Pinches, dashes and handfuls can't be halved meaningfully; never go below 1.
ROUND_UP_UNITS = {"pinch", "dash", "drop", "handful"}  # a unit is "good enough" if rounding moves the amount by 6% or less


def _rounding_error(q):
    _, value, _ = format_us(q)
    return abs((value or 0) - q) / q if q else 0


def _tidy_us(amount_base, kind):
    """Choose the US unit that gives the cleanest measurement for an amount in ml or g."""
    ladder = US_VOLUME_LADDER if kind == "volume" else US_WEIGHT_LADDER
    table = VOLUME_ML if kind == "volume" else WEIGHT_G
    for unit, minimum in ladder:
        q = amount_base / table[unit]
        if q >= minimum * 0.999 and q > 0 and _rounding_error(q) <= PICK_TOLERANCE:
            return unit, q
    smallest = ladder[-1][0]
    return smallest, amount_base / table[smallest]


def _tidy_metric(amount_base, kind):
    if kind == "volume":
        return ("liter", amount_base / 1000) if amount_base >= 1000 else ("milliliter", amount_base)
    if amount_base >= 1000:
        return "kilogram", amount_base / 1000
    if amount_base < 1:
        return "milligram", amount_base * 1000
    return "gram", amount_base


def convert_amount(quantity, unit, system):
    """Re-express an amount in 'us' or 'metric' units, choosing the clearest unit."""
    kind = unit_kind(unit)
    if kind is None or quantity is None:
        return unit, quantity
    base = quantity * (VOLUME_ML if kind == "volume" else WEIGHT_G)[unit]
    if system == "metric":
        return _tidy_metric(base, kind)
    return _tidy_us(base, kind)


def _system_of(unit):
    return "metric" if unit in METRIC_UNITS else "us"


# --- Building the output line --------------------------------------------------

def _unit_label(unit, shown_value):
    if unit is None:
        return ""
    if unit in SHORT:
        return SHORT[unit]
    plural = shown_value is not None and (shown_value > 1 or shown_value == 0)
    return PLURALS.get(unit, unit) if plural else unit


def _fmt(v, unit):
    """(text, shown_value) for one number in this unit."""
    if unit in METRIC_UNITS:
        text = format_metric(v)
        return text, float(text)
    text, value, _ = format_us(v)
    return text, value


def _amount(q, q_max, unit):
    """Return (amount_text, unit_label, approximate)."""
    if q is None:
        return "", "", False
    if unit not in METRIC_UNITS and format_us(q)[0] is None:  # less than 1/16
        return "pinch of" if unit_kind(unit) else "a little", "", True
    text, shown = _fmt(q, unit)
    approx = unit not in METRIC_UNITS and not format_us(q)[2]
    if q_max is not None:
        max_text, shown = _fmt(q_max, unit)
        text = f"{text}-{max_text}"
    return text, _unit_label(unit, shown), approx


def _join_amount(amount, label, unit):
    if not amount:
        return ""
    if unit in SHORT:
        return f"{amount}{label}"
    return f"{amount} {label}".strip()


def build_text(parsed, amount, label, unit):
    """Rebuild a line from parsed parts (used when the original wording can't be kept)."""
    parts = [_join_amount(amount, label, unit)]
    if parsed.get("size"):
        size = parsed["size"]
        parts.append(f"({size})" if size[:1].isdigit() else size)
    if parsed.get("ingredient"):
        parts.append(parsed["ingredient"])
    text = " ".join(p for p in parts if p)
    if parsed.get("prep"):
        text += f", {parsed['prep']}"
    for note in parsed.get("notes") or []:
        text += f", {note}"
    return text.strip()


_UNIT_ALIASES_SORTED = None


def _strip_lead(text):
    """Split 'normalized line' into (prefix kept before unit, rest after unit).

    '1 (14.5 oz) can diced tomatoes' -> ('(14.5 oz)', 'diced tomatoes')
    '3 large eggs'                    -> ('large', 'eggs')
    Returns None when the line doesn't have the simple shape this expects.
    """
    import ingredient_parser as ip

    t = ip._normalize(text)
    m = re.match(r"^(" + ip._NUM + r")(?:" + ip._RANGE_SEP + r"(" + ip._NUM + r"))?\s*", t)
    if m:
        t = t[m.end():]
    else:
        mw = re.match(r"^(\w+)\b\s*", t)
        if not (mw and mw.group(1).lower() in ip.WORD_NUMBERS):
            return None
        t = t[mw.end():]
        if mw.group(1).lower() == "half":
            t = re.sub(r"^(?:a|an)\s+", "", t, flags=re.I)
    if re.match(r"^[x×]\s*\d", t):
        return None
    prefix = []
    while True:
        mp = re.match(r"^(\([^)]*\))\s*", t)
        if mp:
            prefix.append(mp.group(1)); t = t[mp.end():]; continue
        ms = re.match(r"^(extra[- ]large|" + "|".join(sorted(ip.SIZE_WORDS, key=len, reverse=True)) + r")\b\s*", t, flags=re.I)
        if ms:
            prefix.append(ms.group(1)); t = t[ms.end():]; continue
        break
    _, _, rest = ip._match_unit(t)
    return " ".join(prefix), rest


def _plural(word):
    lw = word.lower()
    if lw.endswith(("s", "x", "z", "ch", "sh")) or lw in ("tomato", "potato"):
        return word + "es"
    if lw.endswith("y") and len(lw) > 1 and lw[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _singular(word):
    lw = word.lower()
    if lw.endswith("ies") and len(lw) > 3:
        return word[:-3] + "y"
    if lw.endswith(("oes", "ches", "shes", "xes", "sses")):
        return word[:-2]
    if lw.endswith("s") and not lw.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _match_number(rest, ingredient, shown):
    """'2 lemon' -> '2 lemons', '1 large eggs' -> '1 large egg' (unitless items only)."""
    words = ingredient.split()
    if not words or shown is None:
        return rest
    head = words[-1]
    want_plural = shown > 1
    is_plural = _singular(head) != head
    if want_plural == is_plural:
        return rest
    new_head = _plural(head) if want_plural else _singular(head)
    new_ingredient = " ".join(words[:-1] + [new_head])
    return rest.replace(ingredient, new_ingredient, 1) if ingredient in rest else rest


# --- Public functions ----------------------------------------------------------

def _process(line, factor=1.0, system=None, tidy=True):
    parsed = parse_ingredient(line)
    q, q_max, unit = parsed["quantity"], parsed["quantity_max"], parsed["unit"]
    changed = q is not None

    if q is not None:
        q = q * factor
        if q_max is not None:
            q_max = q_max * factor

        if unit in ROUND_UP_UNITS:
            q = max(1, round(q))
            q_max = max(q, round(q_max)) if q_max is not None else None

        kind = unit_kind(unit)
        if kind:
            target = system or _system_of(unit)
            loose = (parsed.get("size") or "").split(",")[0] in LOOSE_SIZES
            if (tidy and not loose) or target != _system_of(unit):
                new_unit, new_q = convert_amount(q, unit, target)
                if q_max is not None:
                    ratio = new_q / q if q else 1
                    q_max = q_max * ratio
                unit, q = new_unit, new_q

    amount, label, approx = _amount(q, q_max, unit)
    extra_amount = False
    if not changed:
        text = parsed["original"].strip()
    else:
        split = _strip_lead(parsed["original"])
        if split is not None:
            prefix, rest = split
            if not prefix or unit in SHORT:
                pieces = [_join_amount(amount, label, unit), prefix]
            else:
                # "2 (14.5 oz) cans", "6 large eggs", "4 heaping tablespoons"
                pieces = [amount, prefix, label]
            if re.search(r"(?<![\w(])\d", re.sub(r"\([^)]*\)", "", rest)):
                extra_amount = True
            if not unit and parsed["ingredient"]:
                rest = _match_number(rest, parsed["ingredient"], q_max if q_max is not None else q)
            pieces.append(rest)
            text = re.sub(r"\s+", " ", " ".join(p for p in pieces if p)).strip()
        else:
            text = build_text(parsed, amount, label, unit)

    result = {
        "original": parsed["original"],
        "text": text,
        "quantity": _number(q) if q is not None else None,
        "quantity_max": _number(q_max) if q_max is not None else None,
        "quantity_display": amount or None,
        "unit": unit,
        "ingredient": parsed["ingredient"],
        "prep": parsed["prep"],
        "notes": parsed["notes"],
        "scaled": changed,
        "approximate": approx,
    }
    if extra_amount:
        result["tip"] = "This line has more than one amount; only the first was scaled, so check the rest."
        return result
    # Whole items (eggs, cans, lemons) can't be split cleanly; give a hint.
    if changed and unit_kind(unit) is None and q is not None and abs(q - round(q)) > 0.05:
        shown = format_us(q)[0] or "a little"
        if q < 1:
            result["tip"] = f"Works out to {shown}; use part of one or round up to 1."
        else:
            result["tip"] = f"Works out to {shown}; round to {int(q)} or {int(q) + 1} as you prefer."
    return result


def scale_lines(lines, factor, system=None, tidy=True):
    return [_process(l, factor=factor, system=system, tidy=tidy) for l in lines]


def convert_lines(lines, system):
    return [_process(l, factor=1.0, system=system, tidy=True) for l in lines]


def convert_unit(quantity, from_unit, to_unit):
    """Exact conversion of one amount between two units of the same kind."""
    src, dst = canonical_unit(from_unit), canonical_unit(to_unit)
    if not src or not dst:
        bad = from_unit if not src else to_unit
        raise ValueError(f"Unknown unit: {bad}")
    if unit_kind(src) != unit_kind(dst):
        raise ValueError(
            f"Can't convert {unit_kind(src)} ({src}) to {unit_kind(dst)} ({dst}) "
            "without knowing the ingredient's density"
        )
    table = VOLUME_ML if unit_kind(src) == "volume" else WEIGHT_G
    value = quantity * table[src] / table[dst]
    if dst in METRIC_UNITS:
        display = format_metric(value)
    else:
        display = format_us(value)[0] or (f"{value:.3g}" if value else "0")
    return {
        "quantity": quantity, "from": src, "to": dst,
        "result": round(value, 4), "result_display": display,
    }
