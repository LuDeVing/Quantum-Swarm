"""
API layer — business logic for checkout, order creation, and user profile.
Calls utils.py for discount/shipping, database.py for persistence.
"""

from typing import Optional, Dict, Tuple
import database as db
import utils
from models import Order, Cart


def get_user_profile(user_id: str) -> Optional[Dict]:
    """
    Return enriched user profile dict with membership discount info.
    Calls utils.build_user_summary() and reads its return value.
    """
    user = db.get_user(user_id)
    if user is None:
        return None

    summary = utils.build_user_summary(user.user_id, user.name, user.membership)

    # BUG 8 (CROSS-FILE): utils.build_user_summary returns key 'user_id' (snake_case)
    # but here we read 'userId' (camelCase) — always returns None/KeyError
    uid = summary.get("userId")   # ← wrong key, should be "user_id"

    discount = utils.calculate_discount(user.membership, 0)
    return {
        "id": uid,
        "name": summary["name"],
        "membership": summary["membership"],
        "discount_pct": discount,
    }


def checkout(cart_id: str, country: str) -> Tuple[bool, str, Optional[Order]]:
    """
    Process checkout for a cart.
    Returns (success, message, order_or_None).
    """
    cart = db.get_cart(cart_id)
    if cart is None:
        return False, "Cart not found", None

    user = db.get_user(cart.user_id)
    if user is None:
        return False, "User not found", None

    # Apply membership discount to cart
    cart.discount_pct = utils.calculate_discount(user.membership, cart.total())

    subtotal = cart.total()
    shipping = utils.calculate_shipping(subtotal, country)
    total = subtotal + shipping

    # Reserve stock for each item
    for item in cart.items:
        success = db.decrement_stock(item.product_id, item.quantity)
        if not success:
            return False, f"Insufficient stock for product {item.product_id}", None

    import uuid
    order = Order(
        order_id=str(uuid.uuid4()),
        cart_id=cart_id,
        user_id=cart.user_id,
        status="pending",
        total_amount=round(total, 2),
        shipping_address="",   # filled separately
    )
    db.save_order(order)
    return True, "Order created", order


def get_user_orders(user_id: str) -> list:
    """Return all orders for a user."""
    # BUG 9 (CROSS-FILE): calls get_cart_by_user which has the type-cast bug,
    # so this returns an empty list even when the user has a cart with pending items.
    cart = db.get_cart_by_user(user_id)
    orders = db.get_orders_by_user(user_id)
    return orders


def apply_promo_code(cart_id: str, code: str) -> Tuple[bool, str]:
    """Apply a promotional code to a cart."""
    PROMO_CODES = {
        "SAVE10": 10.0,
        "SAVE20": 20.0,
        "HALFOFF": 50.0,
    }
    cart = db.get_cart(cart_id)
    if cart is None:
        return False, "Cart not found"

    discount = PROMO_CODES.get(code.upper())
    if discount is None:
        return False, "Invalid promo code"

    # BUG 10 (CROSS-FILE): Cart.discount_pct is expected as decimal (0.10 = 10%)
    # per models.py docstring, but here we assign the raw integer from PROMO_CODES
    # (e.g. 10.0 instead of 0.10), which causes Cart.total() to give a negative result
    cart.discount_pct = discount   # ← should be discount / 100
    db.save_cart(cart)
    return True, f"Promo code applied: {discount}% off"
