import json

import pytest

from emporio_agent import config
from emporio_agent.tools import (
    escalate_to_human,
    format_brl,
    get_order_status,
    get_product_details,
    get_tool_schemas,
    max_installments,
    run_tool,
    search_products,
)


@pytest.fixture(autouse=True)
def pinned_clock(monkeypatch):
    monkeypatch.setenv("STORE_REFERENCE_DATETIME", "2026-03-25")


def names(result, key="results"):
    return [p["name"] for p in result[key]]


# --- helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(2199, "R$ 2.199,00"), (159.9, "R$ 159,90"), (11499, "R$ 11.499,00"), (5519.08, "R$ 5.519,08")],
)
def test_format_brl(value, expected):
    assert format_brl(value) == expected


@pytest.mark.parametrize(
    ("price", "expected"),
    [(2199, 12), (159.9, 3), (323.10, 4), (99, 1)],  # 323.10 / 5 < R$ 80; 99 / 2 < R$ 50
)
def test_max_installments_follows_policy_tiers(price, expected):
    assert max_installments(price) == expected


# --- search_products --------------------------------------------------------


@pytest.mark.parametrize("query", ["Takamine GD20", "takamine gd 20", "TAKAMINI GD-20", "gd20"])
def test_search_finds_product_despite_spacing_case_and_typos(query):
    result = search_products(query)
    assert names(result) == ["Takamine GD20 Dreadnought Natural"]
    assert result["results"][0]["price"] == "R$ 2.199,00"


def test_search_guitars_up_to_1000_lists_only_available_ones():
    result = search_products(category="Violões", max_price=1000)
    assert result["total_available"] == 12
    assert names(result)[0] == "Tagima Memphis AC-39 Nylon Natural"  # cheapest first
    unavailable = {p["name"]: p["availability"] for p in result["unavailable_matches"]}
    assert unavailable == {
        "Giannini GF-3D Dreadnought Sunburst": "esgotado",
        "Shelby SN-7C 7 Cordas Nylon Natural": "descontinuado",
    }


def test_category_accepts_free_text_and_plural():
    assert search_products(category="violão")["total_available"] == search_products(category="Violões")[
        "total_available"
    ]
    assert search_products("guitarras fender")["total_available"] == 2


def test_price_filter_uses_promotional_price():
    # Crafter HT-100 costs R$ 2.399 but is R$ 1.967,18 with its active 18% promotion.
    result = search_products("crafter ht-100", max_price=2000)
    assert names(result) == ["Crafter HT-100 Folk Aço Natural"]
    assert result["results"][0]["promotion"]["promotional_price"] == "R$ 1.967,18"


def test_out_of_catalog_items_return_nothing():
    assert search_products("pedal de guitarra")["total_available"] == 0
    assert search_products(category="Cordas Orquestrais")["total_available"] == 0


def test_unknown_category_returns_valid_options():
    result = search_products(category="sintetizador modular")
    assert "error" in result and "Violões" in result["valid_categories"]


def test_numbers_sent_as_strings_are_accepted():
    result = search_products(category="Ukuleles", max_price="R$ 1.000,00", limit="5")
    assert result["total_available"] == 11 and len(result["results"]) == 5


# --- get_product_details ----------------------------------------------------


def test_details_without_promotion_has_pix_price():
    details = get_product_details(95)
    assert details["pix_price"] == "R$ 2.089,05"
    assert details["credit_card"] == {"max_interest_free_installments": 12, "installment_value": "R$ 183,25"}


def test_details_with_promotion_has_no_pix_discount():
    details = get_product_details(127)
    assert details["promotion"]["promotional_price"] == "R$ 323,10"
    assert details["pix_price"] is None
    assert details["credit_card"]["max_interest_free_installments"] == 4


def test_details_of_unknown_product():
    assert "error" in get_product_details(9999)
    assert "error" in get_product_details("abc")


# --- get_order_status -------------------------------------------------------


@pytest.mark.parametrize(
    "contact", ["(67) 98432-1098", "67984321098", "+55 67 98432-1098", "98432-1098", "Pedro.Oliveira@jmail.com"]
)
def test_order_is_returned_when_contact_matches(contact):
    order = get_order_status(1, contact)
    assert order["status"] == "Entregue"
    assert order["total_paid"] == "R$ 11.499,00"
    assert order["customer_first_name"] == "Pedro"


def test_order_of_another_customer_and_missing_order_look_the_same():
    other_customers_order = get_order_status(1, "lucas.mendes@jmail.com")  # order 1 is Pedro's
    missing_order = get_order_status(999, "lucas.mendes@jmail.com")
    assert "error" in other_customers_order
    assert other_customers_order == missing_order


def test_order_result_never_exposes_contact_data():
    order = json.dumps(get_order_status(1, "67984321098"))
    assert "98432" not in order and "@" not in order and "Oliveira" not in order


def test_order_lookup_requires_contact():
    assert "error" in get_order_status(1, "")


def test_delivered_order_has_day_counts():
    order = get_order_status(7, "leticia.rocha@jmail.com")  # delivered, estimated 17/02/2026
    assert order["days_since_delivery"] == 36
    assert order["days_since_order"] == 50


def test_overdue_shipment_is_flagged():
    assert get_order_status(8, "(67) 99654-7821")["delivery_overdue"] is True


def test_cancelled_order_includes_reason():
    order = get_order_status(18, "gustavo.nunes@inlook.com")
    assert order["status"] == "Cancelado"
    assert order["notes"] == "Item fora de estoque no momento do pedido"


# --- escalate_to_human ------------------------------------------------------


def test_escalation_writes_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HANDOFF_FILE", tmp_path / "handoffs.jsonl")
    result = escalate_to_human("reclamação", "Cliente recebeu instrumento riscado.", "pedido 5")
    assert result["protocol"].startswith("EMP-20260325-")
    ticket = json.loads((tmp_path / "handoffs.jsonl").read_text(encoding="utf-8"))
    assert ticket["summary"] == "Cliente recebeu instrumento riscado."
    assert "error" in escalate_to_human("reclamação", "  ")


# --- schemas and dispatcher -------------------------------------------------


def test_schemas_use_docstrings_and_real_categories():
    schemas = {s["function"]["name"]: s["function"] for s in get_tool_schemas()}
    assert set(schemas) == {"search_products", "get_product_details", "get_order_status", "escalate_to_human"}
    assert schemas["get_order_status"]["description"].startswith("Look up an order.")
    assert "Violões" in schemas["search_products"]["parameters"]["properties"]["category"]["enum"]


def test_run_tool_returns_json_result():
    result = json.loads(run_tool("get_product_details", '{"product_id": 95}'))
    assert result["name"] == "Takamine GD20 Dreadnought Natural"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("does_not_exist", "{}"),
        ("search_products", "not json"),
        ("search_products", "[1, 2]"),
        ("get_order_status", '{"order_id": 1}'),  # missing phone_or_email
        ("get_product_details", '{"product_id": 95, "extra": 1}'),
    ],
)
def test_run_tool_never_raises(name, arguments):
    assert "error" in json.loads(run_tool(name, arguments))
