# Recipe Scaler API

Scale a recipe up or down and convert between US and metric units, with output written the
way cooks actually measure: `"2 2/3 tablespoons"`, not `"0.1667 cups"`.

Send `"1 1/2 cups flour"` with a factor of 2 and get back:

```json
{
  "original": "1 1/2 cups flour",
  "text": "3 cups flour",
  "quantity": 3,
  "quantity_max": null,
  "quantity_display": "3",
  "unit": "cup",
  "ingredient": "flour",
  "prep": null,
  "notes": [],
  "scaled": true,
  "approximate": false
}
```

What it handles:

- **Kitchen-friendly amounts.** Results round to measurable fractions (1/8, 1/4, 1/3, 1/2, 2/3, 3/4…).
  If rounding moved an amount more than 3%, `approximate` is `true`.
- **Unit tidying.** `8 tbsp` becomes `1/2 cup`, `48 tsp` becomes `1 cup`, `24 oz` becomes `1 1/2 pounds`.
  Turn this off with `"tidy_units": false`. "Heaping" and "scant" spoonfuls keep their unit.
- **Whole items.** Eggs, cans and lemons that come out fractional get a `tip`
  (`"Works out to 1 1/2; round to 1 or 2 as you prefer."`). Nouns follow the number
  (`1 lemon` → `2 lemons`, `3 eggs` → `1 egg`).
- **Pinches and dashes** never drop below 1.
- **Lines with no amount** (`"Salt and pepper to taste"`) come back unchanged with `"scaled": false`.
- **Lines with a second amount** (`"2 large or 3 small potatoes"`) scale the first and add a `tip` to check the rest.
- Parsing is shared with the Ingredient Parser API: fractions (`1/2`, `1½`), ranges (`2-3`),
  can sizes (`1 (14.5 oz) can`), size words, prep and notes.

Volume-to-weight conversion (cups of flour → grams) depends on the ingredient's density and
isn't supported yet; `/convert-unit` returns a clear error if you ask for it.

## Endpoints

| Method | Path | Body |
|---|---|---|
| GET | `/health` | none |
| POST | `/scale` | `{"ingredients": [...], "servings": 4, "target_servings": 9}` or `{"ingredients": [...], "factor": 1.5}` |
| POST | `/convert` | `{"ingredients": [...], "to": "metric"}` (or `"us"`) |
| POST | `/convert-unit` | `{"quantity": 2, "from": "cups", "to": "ml"}` |

- `ingredients` can be a list of lines or one string with a line per ingredient (max 100 lines).
- `/scale` also takes `"system": "us" | "metric"` to scale and convert in one call, and `"tidy_units"`.
- Scaling factors are limited to between 1/100 and 100.

Example `/convert-unit` response:

```json
{"quantity": 2, "from": "cup", "to": "milliliter", "result": 473.176, "result_display": "475"}
```

## Run locally

```
pip install -r requirements.txt
python app.py
pip install pytest && pytest
```

## Deploy on Render (new web service)

1. Put these files in a new GitHub repo (`recipe-scaler-api`).
2. Render → New → Web Service → pick the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`

## List on RapidAPI

1. Add a new API in your RapidAPI provider dashboard; base URL = your Render URL.
2. Add the `/scale`, `/convert` and `/convert-unit` endpoints.
3. Copy the **X-RapidAPI-Proxy-Secret** from the API's settings and set it on Render as the
   environment variable `RAPIDAPI_PROXY_SECRET`. After that, only requests that come through
   RapidAPI are accepted (`/health` stays open).

`ingredient_parser.py` is a copy of the one in the Ingredient Parser API repo. If you improve
the parser there, copy it here too.
