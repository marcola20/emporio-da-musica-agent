from datetime import date, datetime

import pytest

from emporio_agent import config
from emporio_agent.data import DataError, load_policies, load_store


@pytest.fixture(scope="module")
def store():
    return load_store()


def test_loads_all_tables(store):
    assert len(store.categories) == 9
    assert len(store.products) == 65
    assert len(store.customers) == 50
    assert len(store.orders) == 20
    assert sum(len(o.items) for o in store.orders.values()) == 22


def test_product_is_cleaned_and_joined(store):
    gd20 = store.products[95]
    assert gd20.name == "Takamine GD20 Dreadnought Natural"
    assert gd20.category_name == "Violões"
    assert gd20.price == 2199.0
    assert gd20.specs["top"] == "Cedro Sólido"
    assert gd20.promotion is None  # its 12% promotion exists but is inactive


def test_only_active_promotions_are_attached(store):
    with_promo = {p.id: p.promotion.discount_percent for p in store.products.values() if p.promotion}
    assert with_promo == {127: 10, 121: 20, 90: 18, 94: 8}
    assert store.products[94].final_price == pytest.approx(5519.08)  # Taylor 110e, 5999 - 8%


@pytest.mark.parametrize(
    ("product_id", "available", "label"),
    [
        (95, True, "disponível"),
        (96, False, "esgotado"),  # active, stock 0
        (113, False, "descontinuado"),
        (136, False, "descontinuado"),  # discontinued even though stock is 13
        (130, False, "em breve"),  # coming soon even though stock is 2
    ],
)
def test_status_overrides_stock(store, product_id, available, label):
    product = store.products[product_id]
    assert product.available is available
    assert product.availability_label == label


def test_customer_contact_is_normalized(store):
    lucas = store.customers[1]
    assert lucas.phone_digits == "67998123456"
    assert lucas.email == "lucas.mendes@jmail.com"
    assert lucas.first_name == "Lucas"


def test_order_fields_and_labels(store):
    order = store.orders[15]
    assert order.order_date == date(2026, 3, 18)
    assert [i.product_name for i in order.items] == ["Yamaha C70 Nylon Natural", "Taylor 214ce Elétrico Aço Natural"]
    assert order.payment_label == "Cartão de crédito em 12x"
    assert order.status_label == "Pendente"
    assert order.tracking_code is None and order.estimated_delivery is None


def test_order_total_is_the_recorded_one(store):
    # 2 x R$ 1.749 = R$ 3.498 at today's prices, but the customer paid R$ 3.450.
    assert store.orders[3].total == 3450.0


def test_missing_data_dir_raises_clear_error(tmp_path):
    with pytest.raises(DataError, match="not found"):
        load_store(tmp_path)


def test_policies_are_loaded():
    policies = load_policies()
    assert "Direito de Arrependimento" in policies
    assert "Rua 14 de Maio, 3200" in policies


def test_reference_datetime_pins_the_clock(monkeypatch):
    monkeypatch.setenv("STORE_REFERENCE_DATETIME", "2026-03-25")
    assert config.now().replace(tzinfo=None) == datetime(2026, 3, 25, 10, 0)
    monkeypatch.setenv("STORE_REFERENCE_DATETIME", "2026-03-28T20:15")
    assert config.now().replace(tzinfo=None) == datetime(2026, 3, 28, 20, 15)
