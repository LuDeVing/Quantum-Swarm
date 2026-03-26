"""
Validation logic — checks user eligibility and cart validity before checkout.
"""

from typing import List, Tuple
import database as db
from models import Cart, User


def validate_user_age(user: User) -> Tuple[bool, str]:
    """Users must be 18 or older to place orders."""
    # BUG 11 (CROSS-FILE): User.age is defined as int in models.py
    # but here we compare against the string "18" — comparison always works
    # in Python (int vs str raises TypeError at runtime, not caught silently)
    # This would crash on any real User object.
    if user.age < "18":    # ← should be: user.age < 18  (int comparison)
        return False, f"User must be 18+, got age={user.age}"
    return True, "ok"


def validate_cart_not_empty(cart: Cart) -> Tuple[bool, str]:
    """Cart must have at least one item."""
    if len(cart.items) == 0:
        return False, "Cart is empty"
    return True, "ok"


def validate_stock_available(cart: Cart) -> Tuple[bool, str]:
    """Check all items have sufficient stock without reserving it."""
    for item in cart.items:
        product = db.get_product(item.product_id)
        if product is None:
            return False, f"Product {item.product_id} not found"
        if product.stock < item.quantity:
            return False, f"Insufficient stock for {item.product_id}: have {product.stock}, need {item.quantity}"
    return True, "ok"


def validate_checkout(user_id: str, cart_id: str) -> Tuple[bool, List[str]]:
    """Run all checkout validations. Returns (all_passed, list_of_errors)."""
    errors = []

    user = db.get_user(user_id)
    if user is None:
        return False, ["User not found"]

    cart = db.get_cart(cart_id)
    if cart is None:
        return False, ["Cart not found"]

    ok, msg = validate_user_age(user)
    if not ok:
        errors.append(msg)

    ok, msg = validate_cart_not_empty(cart)
    if not ok:
        errors.append(msg)

    ok, msg = validate_stock_available(cart)
    if not ok:
        errors.append(msg)

    return len(errors) == 0, errors
