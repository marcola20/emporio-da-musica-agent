"""Loads the store CSVs into typed, cleaned records.

The original files in data/ are never modified: every cleaning rule lives here, so it is
reproducible and reviewable. The dataset is tiny (~150 rows), so plain lists and dicts in
memory are enough; no database or pandas needed.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from . import config

CSV_NAME = "desafio_tecnico_ai_eng - {table}.csv"

# Raw status codes -> labels the agent can show customers (in Portuguese).
PRODUCT_STATUS_LABELS = {
    "active": "ativo",
    "discontinued": "descontinuado",
    "coming_soon": "em breve",
}
ORDER_STATUS_LABELS = {
    "pending": "Pendente",
    "confirmed": "Confirmado",
    "shipped": "Enviado",
    "delivered": "Entregue",
    "cancelled": "Cancelado",
}
PAYMENT_LABELS = {
    "pix": "PIX",
    "debit": "Cartão de débito",
    "boleto": "Boleto bancário",
}


class DataError(RuntimeError):
    """Raised when a data file is missing or malformed."""


@dataclass(frozen=True)
class Promotion:
    name: str
    discount_percent: int


@dataclass(frozen=True)
class Product:
    id: int
    name: str
    category_id: int
    category_name: str
    price: float
    description: str
    stock: int
    status: str  # raw code: active | discontinued | coming_soon
    specs: dict
    promotion: Promotion | None = None

    @property
    def available(self) -> bool:
        # The status field is authoritative: a discontinued or coming-soon product is not
        # sold even if the stock column says otherwise (the data has such cases).
        return self.status == "active" and self.stock > 0

    @property
    def availability_label(self) -> str:
        if self.status != "active":
            return PRODUCT_STATUS_LABELS.get(self.status, self.status)
        return "disponível" if self.stock > 0 else "esgotado"

    @property
    def final_price(self) -> float:
        """Price the customer pays (promotional price when a promotion is active)."""
        if self.promotion is None:
            return self.price
        return round(self.price * (1 - self.promotion.discount_percent / 100), 2)


@dataclass(frozen=True)
class Customer:
    id: int
    name: str
    phone_digits: str  # only digits, e.g. "67998123456"
    email: str  # lowercase
    city: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0]


@dataclass(frozen=True)
class OrderItem:
    product_id: int
    product_name: str
    quantity: int


@dataclass(frozen=True)
class Order:
    id: int
    customer_id: int
    order_date: date
    status: str  # raw code: pending | confirmed | shipped | delivered | cancelled
    total: float  # as recorded at purchase time; never recomputed from current prices
    payment_method: str  # raw code, e.g. "credit_6x"
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: list[OrderItem] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return ORDER_STATUS_LABELS.get(self.status, self.status)

    @property
    def payment_label(self) -> str:
        installments = re.fullmatch(r"credit_(\d+)x", self.payment_method)
        if installments:
            return f"Cartão de crédito em {installments.group(1)}x"
        return PAYMENT_LABELS.get(self.payment_method, self.payment_method)


@dataclass(frozen=True)
class Store:
    categories: dict[int, str]
    products: dict[int, Product]
    customers: dict[int, Customer]
    orders: dict[int, Order]


def only_digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _read_csv(data_dir: Path, table: str) -> list[dict[str, str]]:
    path = data_dir / CSV_NAME.format(table=table)
    if not path.is_file():
        raise DataError(f"Data file not found: {path}")
    with path.open(encoding="utf-8", newline="") as f:
        # Strip stray whitespace in every cell; empty cells become "".
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _optional(value: str) -> str | None:
    return value or None


def _optional_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def _active_promotions(rows: list[dict[str, str]]) -> dict[int, Promotion]:
    """Active promotions by product. Promotions have no dates: is_active is the only signal.

    Promotions are not cumulative (policy 6.2), so if a product ever had two active ones we
    keep the larger discount. Today no product has more than one.
    """
    promos: dict[int, Promotion] = {}
    for row in rows:
        if row["is_active"] != "1":
            continue
        product_id = int(row["product_id"])
        promo = Promotion(name=row["description"], discount_percent=int(row["discount_percent"]))
        current = promos.get(product_id)
        if current is None or promo.discount_percent > current.discount_percent:
            promos[product_id] = promo
    return promos


def load_store(data_dir: Path = config.DATA_DIR) -> Store:
    """Reads and cleans all tables, resolving the relationships between them."""
    try:
        categories = {int(r["category_id"]): r["name"] for r in _read_csv(data_dir, "categories")}
        promos = _active_promotions(_read_csv(data_dir, "promotions"))

        products = {}
        for r in _read_csv(data_dir, "products"):
            product_id = int(r["product_id"])
            products[product_id] = Product(
                id=product_id,
                name=r["name"],
                category_id=int(r["category_id"]),
                category_name=categories[int(r["category_id"])],
                price=float(r["price_brl"]),
                description=r["description"],
                stock=int(r["stock_quantity"]),
                status=r["status"],
                specs=json.loads(r["specs"]) if r["specs"] else {},
                promotion=promos.get(product_id),
            )

        customers = {
            int(r["customer_id"]): Customer(
                id=int(r["customer_id"]),
                name=r["name"],
                phone_digits=only_digits(r["phone"]),
                email=r["email"].lower(),
                city=r["city"],
            )
            for r in _read_csv(data_dir, "customers")
        }

        items_by_order: dict[int, list[OrderItem]] = {}
        for r in _read_csv(data_dir, "order_items"):
            product = products[int(r["product_id"])]
            items_by_order.setdefault(int(r["order_id"]), []).append(
                OrderItem(product_id=product.id, product_name=product.name, quantity=int(r["quantity"]))
            )

        orders = {}
        for r in _read_csv(data_dir, "orders"):
            order_id = int(r["order_id"])
            orders[order_id] = Order(
                id=order_id,
                customer_id=int(r["customer_id"]),
                order_date=date.fromisoformat(r["order_date"]),
                status=r["status"],
                total=float(r["total_brl"]),
                payment_method=r["payment_method"],
                tracking_code=_optional(r["tracking_code"]),
                estimated_delivery=_optional_date(r["estimated_delivery"]),
                notes=_optional(r["notes"]),
                items=items_by_order.get(order_id, []),
            )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise DataError(f"Malformed data in {data_dir}: {exc!r}") from exc

    return Store(categories=categories, products=products, customers=customers, orders=orders)


@lru_cache(maxsize=1)
def get_store() -> Store:
    """The store data, loaded once per process."""
    return load_store()


def load_policies() -> str:
    """The curated policy manual (Markdown) that goes into the system prompt."""
    if not config.POLICIES_FILE.is_file():
        raise DataError(f"Policies file not found: {config.POLICIES_FILE}")
    return config.POLICIES_FILE.read_text(encoding="utf-8")
