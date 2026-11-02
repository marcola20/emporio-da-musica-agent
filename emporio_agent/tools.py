"""Tools the agent can call (function calling).

Design rule: the LLM converses and interprets; this code guarantees what must not go wrong.
Prices, promotions, availability, date arithmetic and access control to order data are all
computed here, deterministically, so the model never has to invent or calculate them.

Each tool returns a JSON-serializable dict. Problems are returned as {"error": "..."} instead
of raised, so the model can recover (e.g. ask the customer for the right order number).
The docstring of each tool is sent to the LLM as the tool description.
"""

from __future__ import annotations

import copy
import difflib
import inspect
import json
import logging
import re
import unicodedata
import uuid
from typing import Any, Callable

from . import config
from .data import Customer, Product, get_store, only_digits

logger = logging.getLogger(__name__)

MAX_RESULTS = 30
PIX_DISCOUNT = 0.05  # policy 3: 5% off the list price, not cumulative with promotions (6.2)
# Policy 3.1: (highest number of installments in the tier, minimum installment value).
INSTALLMENT_TIERS = [(3, 50.0), (6, 80.0), (12, 100.0)]

STOPWORDS = {"de", "da", "do", "das", "dos", "para", "com", "um", "uma", "os", "as", "em", "no", "na"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def format_brl(value: float) -> str:
    """2199.0 -> 'R$ 2.199,00' (Brazilian format, done in code so the model never gets it wrong)."""
    us_format = f"{value:,.2f}"
    return "R$ " + us_format.replace(",", "_").replace(".", ",").replace("_", ".")


def _normalize(text: str) -> str:
    """Lowercase, remove accents and punctuation: 'Violão Aço' -> 'violao aco'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else " " for c in no_accents)


def _stem(token: str) -> str:
    """Crude Portuguese singularization so 'violões' matches 'violão' and 'guitarras' 'guitarra'."""
    if token.endswith(("oes", "aes")):
        return token[:-3] + "ao"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _tokens(text: str) -> list[str]:
    tokens = (_stem(t) for t in _normalize(text).split())
    return [t for t in tokens if (len(t) > 1 or t.isdigit()) and t not in STOPWORDS]


def _match_score(query_tokens: list[str], product: Product) -> int | None:
    """None if the product does not match every query token; otherwise how many matched the name.

    A token matches the name/category if it is part of a word there (so 'gd20', 'gd 20' and
    'GD-20' all work) or is a close typo of one ('takamini' -> 'takamine'). As a fallback it may
    match the start of a word in the description (e.g. 'iniciante').
    """
    name_tokens = _tokens(f"{product.name} {product.category_name}")
    description_tokens = _tokens(product.description)
    in_name = 0
    for qt in query_tokens:
        if any(qt in t for t in name_tokens) or difflib.get_close_matches(qt, name_tokens, n=1, cutoff=0.8):
            in_name += 1
        elif not any(t.startswith(qt) for t in description_tokens):
            return None
    return in_name


def _resolve_categories(category: str) -> set[int] | None:
    """Category ids matching a free-text name ('violão' -> Violões; 'sopro' -> both wind ones)."""
    wanted = _tokens(category)
    matches = set()
    for category_id, name in get_store().categories.items():
        name_tokens = _tokens(name)
        if all(any(t.startswith(w) for t in name_tokens) for w in wanted):
            matches.add(category_id)
    return matches or None


def _to_number(value: Any, kind: type) -> Any:
    """Models sometimes send numbers as strings ('1000', 'R$ 1.000,00', '#12'); accept them."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.replace("R$", "").replace("#", "").strip()
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", value):  # Brazilian thousands separator
            value = value.replace(".", "")
        value = value.replace(",", ".")
    return kind(float(value)) if kind is int else kind(value)


def _promotion_view(product: Product) -> dict | None:
    if product.promotion is None:
        return None
    return {
        "name": product.promotion.name,
        "discount_percent": product.promotion.discount_percent,
        "original_price": format_brl(product.price),
        "promotional_price": format_brl(product.final_price),
    }


def _summary(product: Product) -> dict:
    return {
        "product_id": product.id,
        "name": product.name,
        "category": product.category_name,
        "price": format_brl(product.price),
        "promotion": _promotion_view(product),
        "availability": product.availability_label,
        "stock": product.stock if product.available else 0,
    }


def max_installments(price: float) -> int:
    """Largest number of interest-free installments allowed for a price (policy 3.1)."""
    best = 1
    for n in range(2, INSTALLMENT_TIERS[-1][0] + 1):
        minimum = next(min_value for limit, min_value in INSTALLMENT_TIERS if n <= limit)
        if price / n >= minimum:
            best = n
    return best


def _contact_matches(customer: Customer, contact: str) -> bool:
    """True if the e-mail or phone given by the user belongs to the customer.

    Phones are compared by digits only, accepting the full number with area code
    ('(67) 99812-3456', '67998123456', '+55 67 99812-3456') or the 9-digit local number.
    """
    contact = contact.strip().lower()
    if "@" in contact:
        return contact == customer.email
    digits = only_digits(contact)
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if digits == customer.phone_digits:
        return True
    return len(digits) == 9 and customer.phone_digits.endswith(digits)


def _br_date(value) -> str | None:
    return value.strftime("%d/%m/%Y") if value else None


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def search_products(
    query: str = "",
    category: str = "",
    max_price: float | None = None,
    min_price: float | None = None,
    limit: int = 20,
) -> dict:
    """Search the store catalog by name, brand, model, category and/or price range.

    Use it for any question about which instruments the store sells, prices, promotions or
    availability (e.g. "violões até R$1000", "quanto custa o Takamine GD20?", "tem guitarra
    Fender?"). Returns current prices already formatted, any active promotion with the final
    price, and availability. "results" holds products available for purchase; products that
    match but cannot be sold right now (out of stock, discontinued, coming soon) are listed
    separately in "unavailable_matches". Price filters apply to the price the customer pays
    (the promotional price when there is one). Never state a price or availability without
    calling this tool or get_product_details.
    """
    try:
        max_price = _to_number(max_price, float)
        min_price = _to_number(min_price, float)
        limit = _to_number(limit, int) or 20
    except (TypeError, ValueError):
        return {"error": "max_price, min_price and limit must be numbers."}
    limit = max(1, min(limit, MAX_RESULTS))

    store = get_store()
    candidates = list(store.products.values())

    if category and category.strip():
        category_ids = _resolve_categories(category)
        if category_ids is None:
            return {
                "error": f"Unknown category '{category}'.",
                "valid_categories": sorted(store.categories.values()),
            }
        candidates = [p for p in candidates if p.category_id in category_ids]

    if max_price is not None:
        candidates = [p for p in candidates if p.final_price <= max_price]
    if min_price is not None:
        candidates = [p for p in candidates if p.final_price >= min_price]

    query_tokens = _tokens(query or "")
    scored = []
    for product in candidates:
        score = _match_score(query_tokens, product) if query_tokens else 0
        if score is not None:
            scored.append((score, product))
    # Best name matches first, then cheapest first.
    scored.sort(key=lambda sp: (-sp[0], sp[1].final_price))

    available = [_summary(p) for _, p in scored if p.available]
    unavailable = [_summary(p) for _, p in scored if not p.available]
    return {
        "total_available": len(available),
        "results": available[:limit],
        "unavailable_matches": unavailable[:10],
    }


def get_product_details(product_id: int) -> dict:
    """Full details of one product by its product_id (from search_products).

    Returns description, technical specs, availability, current price, active promotion,
    the PIX price (5% off, only when there is no promotion) and the maximum number of
    interest-free credit card installments with the installment value. Use it when the
    customer asks about a specific instrument's features, payment options or installments.
    """
    try:
        product_id = _to_number(product_id, int)
    except (TypeError, ValueError):
        return {"error": "product_id must be an integer."}
    product = get_store().products.get(product_id)
    if product is None:
        return {"error": f"No product with product_id {product_id}. Use search_products first."}

    installments = max_installments(product.final_price)
    details = _summary(product)
    details.update(
        {
            "description": product.description,
            "specs": product.specs,
            "pix_price": None if product.promotion else format_brl(product.price * (1 - PIX_DISCOUNT)),
            "pix_note": (
                "PIX discount does not apply on top of a promotional price."
                if product.promotion
                else "5% off the list price for PIX payments."
            ),
            "credit_card": {
                "max_interest_free_installments": installments,
                "installment_value": format_brl(product.final_price / installments),
            },
        }
    )
    return details


def get_order_status(order_id: int, phone_or_email: str) -> dict:
    """Look up an order. Requires the order number AND the phone or e-mail of the buyer.

    Order data is only returned if the contact matches the customer who placed the order
    (identity check, LGPD). Always ask the customer for both pieces of information before
    calling; never guess them. If they don't match, the same generic error is returned whether
    or not the order exists, so the tool cannot be used to discover other people's orders.
    Returns status, items, total paid, payment method, tracking code, estimated delivery,
    cancellation notes, and day counts (since purchase / since delivery) to apply the
    exchange and return policies.
    """
    not_found = {
        "error": (
            "No order found with this number for this phone/e-mail. Ask the customer to check "
            "both. Do not reveal whether the order number exists."
        )
    }
    if not phone_or_email or not str(phone_or_email).strip():
        return {"error": "Ask the customer for the phone number or e-mail used in the purchase."}
    try:
        order_id = _to_number(order_id, int)
    except (TypeError, ValueError):
        return not_found

    store = get_store()
    order = store.orders.get(order_id)
    if order is None or not _contact_matches(store.customers[order.customer_id], str(phone_or_email)):
        return not_found

    today = config.now().date()
    result = {
        "order_id": order.id,
        "customer_first_name": store.customers[order.customer_id].first_name,
        "status": order.status_label,
        "order_date": _br_date(order.order_date),
        "items": [{"product": i.product_name, "quantity": i.quantity} for i in order.items],
        "total_paid": format_brl(order.total),
        "payment_method": order.payment_label,
        "tracking_code": order.tracking_code,
        "estimated_delivery": _br_date(order.estimated_delivery),
        "notes": order.notes,
        "days_since_order": (today - order.order_date).days,
    }
    if order.status == "delivered" and order.estimated_delivery:
        # The data has no actual delivery date; the estimate is the best available proxy.
        result["days_since_delivery"] = (today - order.estimated_delivery).days
        result["delivery_date_note"] = "Delivery date is the estimated one; the actual date is not recorded."
    if order.status == "shipped" and order.estimated_delivery and order.estimated_delivery < today:
        result["delivery_overdue"] = True
    return result


def escalate_to_human(reason: str, summary: str, customer_contact: str = "") -> dict:
    """Open a ticket for the human support team and get a protocol number.

    Use it for complaints, when the customer asks for a human, when a case needs a manager's
    decision (e.g. doubts about applying a policy, returns or exchanges to be processed,
    overdue deliveries), or when you cannot solve the request with the other tools.
    The team replies within 24 business hours. Include a clear summary so the customer does
    not have to repeat themselves.
    """
    if not summary or not str(summary).strip():
        return {"error": "A summary of the case is required."}
    created_at = config.now()
    ticket = {
        "protocol": f"EMP-{created_at:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        "created_at": created_at.isoformat(timespec="seconds"),
        "reason": str(reason).strip(),
        "summary": str(summary).strip(),
        "customer_contact": str(customer_contact).strip(),
    }
    config.HANDOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    with config.HANDOFF_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    return {
        "protocol": ticket["protocol"],
        "message": "Ticket created. A human attendant will reply within 24 business hours.",
    }


# ---------------------------------------------------------------------------
# Schemas sent to the LLM and dispatcher
# ---------------------------------------------------------------------------

_PARAMETERS: dict[str, dict] = {
    "search_products": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free text: name, brand, model or features (e.g. 'Takamine GD20', 'yamaha nylon'). Empty to list by category/price.",
            },
            # The category enum is filled in from categories.csv by get_tool_schemas().
            "category": {"type": "string", "description": "Optional category filter."},
            "max_price": {"type": "number", "description": "Maximum price in BRL."},
            "min_price": {"type": "number", "description": "Minimum price in BRL."},
            "limit": {"type": "integer", "description": "Maximum number of results (default 20, max 30)."},
        },
    },
    "get_product_details": {
        "type": "object",
        "properties": {"product_id": {"type": "integer", "description": "product_id returned by search_products."}},
        "required": ["product_id"],
    },
    "get_order_status": {
        "type": "object",
        "properties": {
            "order_id": {"type": "integer", "description": "Order number given by the customer."},
            "phone_or_email": {
                "type": "string",
                "description": "Phone number or e-mail given by the customer, exactly as typed.",
            },
        },
        "required": ["order_id", "phone_or_email"],
    },
    "escalate_to_human": {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Short category, e.g. 'reclamação', 'troca/devolução', 'atraso na entrega', 'pedido do cliente'.",
            },
            "summary": {"type": "string", "description": "What happened and what the customer needs."},
            "customer_contact": {
                "type": "string",
                "description": "Order number and/or contact the customer provided, if any.",
            },
        },
        "required": ["reason", "summary"],
    },
}

TOOLS: dict[str, Callable[..., dict]] = {
    fn.__name__: fn for fn in (search_products, get_product_details, get_order_status, escalate_to_human)
}

def get_tool_schemas() -> list[dict]:
    """Tool definitions in the OpenAI Chat Completions format (description = docstring)."""
    parameters = copy.deepcopy(_PARAMETERS)
    category = parameters["search_products"]["properties"]["category"]
    category["enum"] = sorted(get_store().categories.values())
    return [
        {
            "type": "function",
            "function": {"name": name, "description": inspect.getdoc(fn), "parameters": parameters[name]},
        }
        for name, fn in TOOLS.items()
    ]


def run_tool(name: str, arguments: str) -> str:
    """Executes a tool call coming from the LLM and returns the result as a JSON string.

    Never raises: unknown tools, malformed arguments and unexpected bugs become an
    {"error": ...} result, so one bad call does not crash the conversation.
    """
    fn = TOOLS.get(name)
    if fn is None:
        result: dict = {"error": f"Unknown tool '{name}'. Available: {', '.join(TOOLS)}."}
    else:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
            inspect.signature(fn).bind(**args)  # rejects missing/unexpected arguments
        except (ValueError, TypeError) as exc:
            result = {"error": f"Invalid arguments for {name}: {exc}"}
        else:
            try:
                result = fn(**args)
            except Exception:
                logger.exception("Tool %s failed with arguments %s", name, arguments)
                result = {"error": f"Internal error in {name}. Apologize and offer a human attendant."}
    return json.dumps(result, ensure_ascii=False)
