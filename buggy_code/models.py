"""
Data models for a simple e-commerce order system.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Product:
    product_id: str
    name: str
    price: float        # price in dollars
    stock: int
    category: str


@dataclass
class CartItem:
    product_id: str
    quantity: int
    unit_price: float

    def subtotal(self) -> float:
        # BUG 1 (within-file): should be quantity * unit_price
        # but uses integer division losing cents
        return (self.quantity * self.unit_price * 100) // 100


@dataclass
class Cart:
    cart_id: str
    user_id: str        # NOTE: stored as string "u_123"
    items: List[CartItem] = field(default_factory=list)
    discount_pct: float = 0.0   # e.g. 0.10 = 10% off

    def total(self) -> float:
        subtotal = sum(item.subtotal() for item in self.items)
        # BUG 2 (within-file): applies discount incorrectly
        # should be subtotal * (1 - discount_pct)
        # but multiplies discount_pct by 100 treating it as percentage points
        return subtotal * (1 - self.discount_pct / 100)


@dataclass
class Order:
    order_id: str
    cart_id: str
    user_id: str        # NOTE: same format "u_123"
    status: str         # "pending", "confirmed", "shipped", "delivered"
    total_amount: float
    shipping_address: str

    def is_shippable(self) -> bool:
        # BUG 3 (within-file): "confirmed" orders should also be shippable
        # but uses == instead of checking a list
        return self.status == "shipped"


@dataclass
class User:
    user_id: str        # format: "u_123"  ← key contract used by other files
    name: str
    email: str
    age: int            # NOTE: integer — validator.py must compare as int
    membership: str     # "free", "premium", "enterprise"
