"""
Utility functions: discount calculation, shipping cost, pagination.
"""

from typing import List, Any, Dict


def calculate_discount(membership: str, subtotal: float) -> float:
    """Returns discount percentage as a decimal (e.g. 0.15 = 15%)."""
    if membership == "premium":
        return 0.15
    elif membership == "enterprise":
        return 0.25
    # BUG 4 (within-file): free tier returns 0.10 instead of 0.0
    # giving all users at least 10% off
    return 0.10


def calculate_shipping(total: float, country: str) -> float:
    """Returns shipping cost in dollars."""
    if country == "US":
        # Free shipping over $50
        if total >= 50:
            return 0.0
        return 5.99
    elif country == "CA":
        if total >= 75:
            return 0.0
        return 12.99
    else:
        # International flat rate
        return 24.99


def paginate(items: List[Any], page: int, page_size: int) -> List[Any]:
    """Return items for the given 1-indexed page."""
    # BUG 5 (within-file): off-by-one — page should be 1-indexed
    # but treats page as 0-indexed, so page=1 skips the first page_size items
    start = page * page_size
    end = start + page_size
    return items[start:end]


def build_user_summary(user_id: str, name: str, membership: str) -> Dict:
    """Build a summary dict for a user.

    IMPORTANT — returns key 'user_id' (snake_case).
    api.py must use this exact key when reading the dict.
    """
    return {
        "user_id": user_id,   # ← key contract: snake_case
        "name": name,
        "membership": membership,
    }


def format_price(amount: float) -> str:
    """Format a dollar amount as a string like '$12.50'."""
    return f"${amount:.2f}"


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp value between min and max."""
    return max(min_val, min(max_val, value))
