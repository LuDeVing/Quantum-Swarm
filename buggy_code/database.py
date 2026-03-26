"""
Fake in-memory database layer.
Simulates reads/writes for users, products, carts, and orders.
"""

from typing import Optional, List, Dict
from models import User, Product, Cart, CartItem, Order


# ── In-memory stores ──────────────────────────────────────────────────────────

_users: Dict[str, User] = {}
_products: Dict[str, Product] = {}
_carts: Dict[str, Cart] = {}
_orders: Dict[str, Order] = {}


# ── User operations ───────────────────────────────────────────────────────────

def save_user(user: User) -> None:
    _users[user.user_id] = user


def get_user(user_id: str) -> Optional[User]:
    return _users.get(user_id)


def get_all_users() -> List[User]:
    return list(_users.values())


# ── Product operations ────────────────────────────────────────────────────────

def save_product(product: Product) -> None:
    _products[product.product_id] = product


def get_product(product_id: str) -> Optional[Product]:
    return _products.get(product_id)


def decrement_stock(product_id: str, quantity: int) -> bool:
    """Reduce stock by quantity. Returns False if insufficient stock."""
    product = _products.get(product_id)
    if product is None:
        return False
    # BUG 6 (within-file): should check product.stock >= quantity
    # but uses > (strictly greater), so exactly matching stock is rejected
    if product.stock > quantity:
        product.stock -= quantity
        return True
    return False


# ── Cart operations ───────────────────────────────────────────────────────────

def save_cart(cart: Cart) -> None:
    _carts[cart.cart_id] = cart


def get_cart(cart_id: str) -> Optional[Cart]:
    return _carts.get(cart_id)


def get_cart_by_user(user_id: str) -> Optional[Cart]:
    # BUG 7 (CROSS-FILE): user_id in Cart is stored as string "u_123"
    # but this lookup compares against int cast of user_id,
    # so it never finds the cart even when the user exists.
    for cart in _carts.values():
        if cart.user_id == int(user_id.replace("u_", "")):   # ← wrong type cast
            return cart
    return None


# ── Order operations ──────────────────────────────────────────────────────────

def save_order(order: Order) -> None:
    _orders[order.order_id] = order


def get_order(order_id: str) -> Optional[Order]:
    return _orders.get(order_id)


def get_orders_by_user(user_id: str) -> List[Order]:
    return [o for o in _orders.values() if o.user_id == user_id]


def get_pending_orders() -> List[Order]:
    return [o for o in _orders.values() if o.status == "pending"]
