"""Parse free-text recipe ingredient lines into structured data.

Pure Python, no dependencies.

    >>> parse_ingredient("2 1/2 cups chopped yellow onion")["quantity"]
    2.5
"""

import re

# --- Fractions -------------------------------------------------------------

UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
    "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}

WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "dozen": 12, "half": 0.5,
}

# --- Units -----------------------------------------------------------------
# canonical name -> (aliases, type)
UNITS = {
    "teaspoon": (["teaspoons", "teaspoon", "tsps", "tsp", "t"], "volume"),
    "tablespoon": (["tablespoons", "tablespoon", "tbsps", "tbsp", "tbls", "tbl", "tbs", "T"], "volume"),
    "fluid ounce": (["fluid ounces", "fluid ounce", "fl. oz.", "fl. oz", "fl oz", "floz"], "volume"),
    "cup": (["cups", "cup", "c"], "volume"),
    "pint": (["pints", "pint", "pt"], "volume"),
    "quart": (["quarts", "quart", "qt"], "volume"),
    "gallon": (["gallons", "gallon", "gal"], "volume"),
    "milliliter": (["milliliters", "millilitres", "milliliter", "millilitre", "ml"], "volume"),
    "liter": (["liters", "litres", "liter", "litre", "l"], "volume"),
    "ounce": (["ounces", "ounce", "oz"], "weight"),
    "pound": (["pounds", "pound", "lbs", "lb"], "weight"),
    "gram": (["grams", "gram", "gr", "g"], "weight"),
    "kilogram": (["kilograms", "kilogram", "kgs", "kg"], "weight"),
    "milligram": (["milligrams", "milligram", "mg"], "weight"),
    "pinch": (["pinches", "pinch"], "other"),
    "dash": (["dashes", "dash"], "other"),
    "drop": (["drops", "drop"], "other"),
    "clove": (["cloves", "clove"], "count"),
    "can": (["cans", "can", "tins", "tin"], "count"),
    "jar": (["jars", "jar"], "count"),
    "package": (["packages", "package", "pkgs", "pkg", "packets", "packet"], "count"),
    "bag": (["bags", "bag"], "count"),
    "box": (["boxes", "box"], "count"),
    "bottle": (["bottles", "bottle"], "count"),
    "stick": (["sticks", "stick"], "count"),
    "slice": (["slices", "slice"], "count"),
    "piece": (["pieces", "piece", "pcs"], "count"),
    "sprig": (["sprigs", "sprig"], "count"),
    "bunch": (["bunches", "bunch"], "count"),
    "head": (["heads", "head"], "count"),
    "stalk": (["stalks", "stalk"], "count"),
    "handful": (["handfuls", "handful"], "other"),
}

# Short, ambiguous aliases matched case-sensitively ("T" = tablespoon, "t" = teaspoon).
CASE_SENSITIVE = {"T", "t"}

_alias_list = []
for _canon, (_aliases, _kind) in UNITS.items():
    for _a in _aliases:
        _alias_list.append((_a, _canon))
_alias_list.sort(key=lambda x: -len(x[0]))  # longest first

SIZE_WORDS = {"small", "medium", "large", "extra-large", "extra large", "jumbo", "heaping", "level", "scant", "generous", "big"}

PREP_WORDS = {
    "chopped", "diced", "minced", "sliced", "grated", "shredded", "crushed",
    "melted", "softened", "beaten", "peeled", "cubed", "julienned", "halved",
    "quartered", "mashed", "toasted", "ground", "cooked", "drained", "rinsed",
    "trimmed", "zested", "juiced", "pitted", "seeded", "cored", "thawed",
    "divided", "packed", "sifted", "room-temperature", "finely", "roughly",
    "coarsely", "thinly", "freshly", "lightly", "firmly",
}

NOTE_PATTERNS = [
    r"\bto taste\b", r"\boptional\b", r"\bfor (?:garnish|serving|dusting|greasing|frying|the pan)\b",
    r"\bas needed\b", r"\bplus more(?: [a-z ]+)?\b", r"\bor more\b", r"\bdivided\b",
]

_NUM = r"(?:\d+\s+\d+/\d+|\d+-\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_RANGE_SEP = r"\s*(?:-|–|—|to|or)\s*"


def _to_number(token):
    token = token.strip()
    m = re.fullmatch(r"(\d+)[\s-]+(\d+)/(\d+)", token)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", token)
    if m:
        d = int(m.group(2))
        return int(m.group(1)) / d if d else None
    try:
        return float(token)
    except ValueError:
        return None


def _clean_number(x):
    if x is None:
        return None
    x = round(x, 3)
    return int(x) if x == int(x) else x


def _normalize(text):
    text = text.strip()
    for uf, ascii_frac in UNICODE_FRACTIONS.items():
        # "1½" -> "1 1/2", "½" -> "1/2"
        text = re.sub(r"(\d)" + uf, r"\1 " + ascii_frac, text)
        text = text.replace(uf, ascii_frac)
    text = text.replace("⁄", "/")
    text = re.sub(r"^[\-\*•·▢•\s]+", "", text)  # bullets / checkboxes
    text = re.sub(r"\s+", " ", text)
    return text


def _match_unit(text):
    """Return (canonical_unit, unit_type, rest) if text starts with a unit."""
    for alias, canon in _alias_list:
        if alias in CASE_SENSITIVE:
            ok = text.startswith(alias)
        else:
            ok = text.lower().startswith(alias.lower())
        if not ok:
            continue
        rest = text[len(alias):]
        # must end at a word boundary (allow trailing period like "tbsp.")
        if rest and rest[0].isalpha():
            continue
        rest = re.sub(r"^\.(?=\s|$)", "", rest).lstrip()
        # "of" after a unit: "2 cups of flour"
        rest = re.sub(r"^of\s+", "", rest, flags=re.I)
        return canon, UNITS[canon][1], rest
    return None, None, text


# Approximate conversion factors to milliliters / grams (US customary volumes).
TO_METRIC = {
    "teaspoon": (4.929, "ml"), "tablespoon": (14.787, "ml"), "fluid ounce": (29.574, "ml"),
    "cup": (236.588, "ml"), "pint": (473.176, "ml"), "quart": (946.353, "ml"),
    "gallon": (3785.41, "ml"), "milliliter": (1, "ml"), "liter": (1000, "ml"),
    "ounce": (28.3495, "g"), "pound": (453.592, "g"), "gram": (1, "g"),
    "kilogram": (1000, "g"), "milligram": (0.001, "g"),
}


def _to_metric(qty, qty_max, unit):
    if qty is None or unit not in TO_METRIC:
        return None
    factor, munit = TO_METRIC[unit]
    out = {"quantity": round(qty * factor, 1), "unit": munit}
    if qty_max is not None:
        out["quantity_max"] = round(qty_max * factor, 1)
    return out


def parse_ingredient(line):
    """Parse one ingredient line. Always returns a dict; never raises on text input."""
    original = line if isinstance(line, str) else ""
    text = _normalize(original)
    result = {
        "original": original,
        "quantity": None,
        "quantity_max": None,
        "unit": None,
        "unit_type": None,
        "size": None,
        "ingredient": None,
        "prep": None,
        "notes": [],
        "metric": None,
    }
    if not text:
        return result

    notes = []

    # Parenthetical notes: "1 (14.5 oz) can tomatoes", "butter (softened)"
    paren_size = None
    paren_prep = []
    for p in re.findall(r"\(([^)]*)\)", text):
        p_stripped = p.strip()
        if re.match(r"^" + _NUM + r"\s*[-–]?\s*[a-zA-Z]", p_stripped) and paren_size is None:
            paren_size = p_stripped
        elif p_stripped and all(w.lower().strip(",.") in PREP_WORDS | {"and"} for w in p_stripped.split()):
            paren_prep.append(p_stripped)
        elif p_stripped:
            notes.append(p_stripped)
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text).strip()

    # Quantity (number, range, or word number)
    m = re.match(r"^(" + _NUM + r")(?:" + _RANGE_SEP + r"(" + _NUM + r"))?\s*", text)
    if m:
        result["quantity"] = _clean_number(_to_number(m.group(1)))
        if m.group(2):
            result["quantity_max"] = _clean_number(_to_number(m.group(2)))
        text = text[m.end():]
        # "2 x 400g tins" style multiplier
        mx = re.match(r"^[x×]\s*", text)
        if mx:
            text = text[mx.end():]
            m2 = re.match(r"^(" + _NUM + r")\s*", text)
            if m2:
                inner = _to_number(m2.group(1))
                text = text[m2.end():]
                unit, utype, rest = _match_unit(text)
                if unit:
                    paren_size = f"{_clean_number(inner)} {unit}"
                    text = rest
    else:
        mw = re.match(r"^(\w+)\b\s*", text)
        if mw and mw.group(1).lower() in WORD_NUMBERS:
            nxt = text[mw.end():]
            # avoid treating "a" as a quantity unless a unit or ingredient follows sensibly
            result["quantity"] = _clean_number(WORD_NUMBERS[mw.group(1).lower()])
            text = nxt
            if mw.group(1).lower() == "half":
                text = re.sub(r"^(?:a|an)\s+", "", text, flags=re.I)

    # Size words before unit: "1 large egg", "2 heaping tablespoons"
    ms = re.match(r"^(extra[- ]large|" + "|".join(sorted(SIZE_WORDS, key=len, reverse=True)) + r")\b\s*", text, flags=re.I)
    if ms:
        result["size"] = ms.group(1).lower()
        text = text[ms.end():]

    unit, utype, text = _match_unit(text)
    result["unit"] = unit
    result["unit_type"] = utype

    if paren_size:
        result["size"] = paren_size if not result["size"] else f"{result['size']}, {paren_size}"

    # Notes like "to taste", "optional"
    for pat in NOTE_PATTERNS:
        for nm in re.finditer(pat, text, flags=re.I):
            notes.append(nm.group(0).lower())
        text = re.sub(r",?\s*" + pat, "", text, flags=re.I)

    # Prep after a comma: "onion, finely diced"
    prep_parts = []
    if "," in text:
        head, tail = text.split(",", 1)
        tail = tail.strip(" ,.")
        if tail:
            prep_parts.append(tail)
        text = head

    # Leading prep words: "chopped yellow onion", "finely chopped parsley"
    words = text.split()
    lead = []
    while words and words[0].lower().strip(",") in PREP_WORDS:
        lead.append(words.pop(0).strip(","))
    # Trailing prep words: "parsley chopped"
    trail = []
    while len(words) > 1 and words[-1].lower().strip(",.") in PREP_WORDS:
        trail.insert(0, words.pop().strip(",."))
    if lead:
        prep_parts.insert(0, " ".join(lead))
    if trail:
        prep_parts.append(" ".join(trail))
    prep_parts.extend(paren_prep)

    ingredient = " ".join(words).strip(" ,.-")
    ingredient = re.sub(r"^(?:of)\s+", "", ingredient, flags=re.I)
    result["ingredient"] = ingredient or None
    result["prep"] = ", ".join(p for p in prep_parts if p).lower() or None

    result["metric"] = _to_metric(result["quantity"], result["quantity_max"], unit)

    seen = set()
    result["notes"] = [n for n in notes if not (n in seen or seen.add(n))]
    return result


def parse_ingredients(lines):
    return [parse_ingredient(l) for l in lines]
