import pytest

from app import app
from scaler import convert_lines, convert_unit, format_us, scale_lines


def text(line, factor, **kw):
    return scale_lines([line], factor, **kw)[0]["text"]


@pytest.mark.parametrize("line,factor,expected", [
    ("1 1/2 cups flour", 2, "3 cups flour"),
    ("1½ cups chopped onion", 0.5, "3/4 cup chopped onion"),
    ("2 tbsp butter, melted", 2, "1/4 cup butter, melted"),
    ("1/2 tsp salt", 2, "1 teaspoon salt"),
    ("1/3 cup milk", 3, "1 cup milk"),
    ("5 tbsp sugar", 3, "15 tablespoons sugar"),
    ("3 large eggs", 2, "6 large eggs"),
    ("3 large eggs", 1 / 3, "1 large egg"),
    ("1 lemon, juiced", 2, "2 lemons, juiced"),
    ("1 cherry tomato", 3, "3 cherry tomatoes"),
    ("1 (14.5 oz) can diced tomatoes, drained", 2, "2 (14.5 oz) cans diced tomatoes, drained"),
    ("2-3 cloves garlic, minced", 2, "4-6 cloves garlic, minced"),
    ("200g plain flour", 1.5, "300g plain flour"),
    ("12 oz chocolate chips", 2, "1 1/2 pounds chocolate chips"),
    ("2 heaping tablespoons cocoa", 2, "4 heaping tablespoons cocoa"),
    ("a pinch of nutmeg", 0.5, "1 pinch nutmeg"),
    ("a pinch of nutmeg", 2, "2 pinches nutmeg"),
    ("Salt and pepper to taste", 3, "Salt and pepper to taste"),
])
def test_scale_text(line, factor, expected):
    assert text(line, factor) == expected


def test_second_amount_gets_flagged():
    r = scale_lines(["2 large or 3 small potatoes"], 2)[0]
    assert "more than one amount" in r["tip"]


def test_unscalable_line_is_marked():
    r = scale_lines(["Salt and pepper to taste"], 2)[0]
    assert r["scaled"] is False and r["quantity"] is None


def test_partial_items_get_a_tip():
    r = scale_lines(["3 large eggs"], 0.5)[0]
    assert r["text"] == "1 1/2 large eggs"
    assert "round to 1 or 2" in r["tip"]


def test_tiny_amount_is_flagged_approximate():
    r = scale_lines(["1/2 tsp salt"], 1 / 3)[0]
    assert r["text"] == "1/8 teaspoon salt"
    assert r["approximate"] is True


def test_keep_units_when_tidy_is_off():
    assert text("8 tbsp butter", 1, tidy=False) == "8 tablespoons butter"
    assert text("8 tbsp butter", 1) == "1/2 cup butter"


@pytest.mark.parametrize("line,system,expected", [
    ("1 cup milk", "metric", "235ml milk"),
    ("1 lb ground beef", "metric", "455g ground beef"),
    ("2 kg potatoes", "us", "4 3/8 pounds potatoes"),
    ("250 ml milk", "us", "1 cup milk"),
    ("15 ml oil", "us", "1 tablespoon oil"),
    ("1 litre stock", "us", "4 1/4 cups stock"),
    ("3 large eggs", "metric", "3 large eggs"),
])
def test_convert(line, system, expected):
    assert convert_lines([line], system)[0]["text"] == expected


def test_convert_unit():
    assert convert_unit(16, "tbsp", "cups")["result_display"] == "1"
    assert convert_unit(1, "cup", "ml")["result"] == pytest.approx(236.588)
    with pytest.raises(ValueError):
        convert_unit(1, "cup", "grams")
    with pytest.raises(ValueError):
        convert_unit(1, "smidgen", "cup")


@pytest.mark.parametrize("x,expected", [(2.5, "2 1/2"), (1 / 3, "1/3"), (0.125, "1/8"), (13.4, "13 1/2"), (3, "3")])
def test_format_us(x, expected):
    assert format_us(x)[0] == expected


# --- HTTP layer -------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("RAPIDAPI_PROXY_SECRET", raising=False)
    app.config["TESTING"] = True
    return app.test_client()


def test_health(client):
    assert client.get("/health").get_json() == {"status": "ok"}


def test_scale_by_servings(client):
    r = client.post("/scale", json={"ingredients": ["2 cups rice", "1 tsp salt"], "servings": 3, "target_servings": 9})
    body = r.get_json()
    assert r.status_code == 200
    assert body["factor"] == 3
    assert [x["text"] for x in body["results"]] == ["6 cups rice", "1 tablespoon salt"]


def test_scale_accepts_text_block(client):
    r = client.post("/scale", json={"ingredients": "1 cup sugar\n\n2 eggs\n", "factor": 2})
    assert [x["text"] for x in r.get_json()["results"]] == ["2 cups sugar", "4 eggs"]


def test_scale_with_metric_output(client):
    r = client.post("/scale", json={"ingredients": ["1 cup milk"], "factor": 2, "system": "metric"})
    assert r.get_json()["results"][0]["text"] == "475ml milk"


@pytest.mark.parametrize("payload", [
    {},
    {"ingredients": []},
    {"ingredients": ["1 cup flour"]},
    {"ingredients": ["1 cup flour"], "factor": 0},
    {"ingredients": ["1 cup flour"], "factor": -2},
    {"ingredients": ["1 cup flour"], "factor": "2"},
    {"ingredients": ["1 cup flour"], "factor": True},
    {"ingredients": ["1 cup flour"], "factor": 1000},
    {"ingredients": ["1 cup flour"], "servings": 4},
    {"ingredients": ["1 cup flour"], "factor": 2, "system": "imperial"},
    {"ingredients": ["1 cup flour"], "factor": 2, "tidy_units": "yes"},
    {"ingredients": ["x"] * 101, "factor": 2},
    {"ingredients": ["x" * 501], "factor": 2},
])
def test_scale_rejects_bad_input(client, payload):
    r = client.post("/scale", json=payload)
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_convert_endpoint(client):
    r = client.post("/convert", json={"ingredients": ["500g flour"], "to": "us"})
    assert r.get_json()["results"][0]["text"] == "1 1/8 pounds flour"
    assert client.post("/convert", json={"ingredients": ["500g flour"]}).status_code == 400


def test_convert_unit_endpoint(client):
    r = client.post("/convert-unit", json={"quantity": 2, "from": "cups", "to": "ml"})
    assert r.get_json()["result_display"] == "475"
    bad = client.post("/convert-unit", json={"quantity": 1, "from": "cup", "to": "g"})
    assert bad.status_code == 400 and "density" in bad.get_json()["error"]
    assert client.post("/convert-unit", json={"quantity": "2", "from": "cup", "to": "ml"}).status_code == 400


def test_proxy_secret_required_when_set(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", "s3cret")
    body = {"ingredients": ["1 cup sugar"], "factor": 2}
    assert client.post("/scale", json=body).status_code == 403
    ok = client.post("/scale", json=body, headers={"X-RapidAPI-Proxy-Secret": "s3cret"})
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200
