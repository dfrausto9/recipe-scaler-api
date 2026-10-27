"""Recipe Scaler API - Flask app.

Endpoints
  GET  /health         -> {"status": "ok"}
  POST /scale          {"ingredients": [...], "servings": 4, "target_servings": 9}
                       or {"ingredients": [...], "factor": 1.5}
                       optional: "system": "us" | "metric", "tidy_units": true
  POST /convert        {"ingredients": [...], "to": "metric" | "us"}
  POST /convert-unit   {"quantity": 2, "from": "cups", "to": "ml"}

"ingredients" can be a list of lines or one string with a line per ingredient.

If the environment variable RAPIDAPI_PROXY_SECRET is set, every request except
/health must carry the matching X-RapidAPI-Proxy-Secret header, so only traffic
coming through RapidAPI is served.
"""

import hmac
import math
import os

from flask import Flask, jsonify, request

from scaler import convert_lines, convert_unit, scale_lines

MAX_LINES = 100
MAX_LINE_LENGTH = 500
MAX_FACTOR = 100
SYSTEMS = ("us", "metric")

app = Flask(__name__)


def _error(message, status=400):
    return jsonify({"error": message}), status


@app.before_request
def check_proxy_secret():
    if request.path == "/health":
        return None
    secret = os.environ.get("RAPIDAPI_PROXY_SECRET")
    if secret:
        sent = request.headers.get("X-RapidAPI-Proxy-Secret", "")
        if not hmac.compare_digest(sent, secret):
            return _error("Forbidden", 403)
    return None


def _positive_number(value):
    """Return value as a float if it's a real, positive number, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _read_lines(data):
    """Return (lines, error_response)."""
    raw = data.get("ingredients")
    if isinstance(raw, str):
        raw = [l for l in raw.splitlines() if l.strip()]
    if not isinstance(raw, list) or not raw:
        return None, _error('Send "ingredients" as a list of lines, e.g. ["2 cups flour", "1 tsp salt"]')
    if len(raw) > MAX_LINES:
        return None, _error(f"A request is limited to {MAX_LINES} ingredient lines")
    if not all(isinstance(l, str) and len(l) <= MAX_LINE_LENGTH for l in raw):
        return None, _error(f"Each ingredient must be text of at most {MAX_LINE_LENGTH} characters")
    return raw, None


def _read_system(data, key, required=False):
    value = data.get(key)
    if value is None and not required:
        return None, None
    if not isinstance(value, str) or value.lower() not in SYSTEMS:
        return None, _error(f'"{key}" must be "us" or "metric"')
    return value.lower(), None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/scale")
def scale():
    data = request.get_json(silent=True) or {}
    lines, err = _read_lines(data)
    if err:
        return err

    if "factor" in data:
        factor = _positive_number(data.get("factor"))
        if factor is None:
            return _error('"factor" must be a positive number, e.g. 2 to double a recipe')
    else:
        servings = _positive_number(data.get("servings"))
        target = _positive_number(data.get("target_servings"))
        if servings is None or target is None:
            return _error('Send "servings" and "target_servings" (e.g. 4 and 9), or a "factor" (e.g. 2)')
        factor = target / servings
    if factor > MAX_FACTOR or factor < 1 / MAX_FACTOR:
        return _error(f"Scaling is limited to between 1/{MAX_FACTOR} and {MAX_FACTOR} times the recipe")

    system, err = _read_system(data, "system")
    if err:
        return err
    tidy = data.get("tidy_units", True)
    if not isinstance(tidy, bool):
        return _error('"tidy_units" must be true or false')

    results = scale_lines(lines, factor, system=system, tidy=tidy)
    return jsonify({
        "factor": round(factor, 4),
        "count": len(results),
        "results": results,
    })


@app.post("/convert")
def convert():
    data = request.get_json(silent=True) or {}
    lines, err = _read_lines(data)
    if err:
        return err
    system, err = _read_system(data, "to", required=True)
    if err:
        return err
    results = convert_lines(lines, system)
    return jsonify({"to": system, "count": len(results), "results": results})


@app.post("/convert-unit")
def convert_one():
    data = request.get_json(silent=True) or {}
    quantity = data.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) \
            or not math.isfinite(quantity) or quantity < 0:
        return _error('Send a non-negative "quantity", e.g. {"quantity": 2, "from": "cups", "to": "ml"}')
    from_unit, to_unit = data.get("from"), data.get("to")
    if not isinstance(from_unit, str) or not isinstance(to_unit, str):
        return _error('Send "from" and "to" units, e.g. {"quantity": 2, "from": "cups", "to": "ml"}')
    try:
        return jsonify(convert_unit(quantity, from_unit, to_unit))
    except ValueError as e:
        return _error(str(e))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
