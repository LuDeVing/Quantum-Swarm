"""Unit tests for desktop_suggest_click JSON parsing (no screen / API)."""

from software_company.tool_registry import _map_image_coords_to_screen, _parse_click_coords_json


def test_parse_plain_json():
    x, y, el = _parse_click_coords_json('{"x": 120, "y": 340, "element": "OK"}')
    assert x == 120 and y == 340 and el == "OK"


def test_parse_markdown_fence():
    raw = """Here:
```json
{"x": 10, "y": 20, "element": "btn"}
```
"""
    x, y, _ = _parse_click_coords_json(raw)
    assert x == 10 and y == 20


def test_parse_null_coords():
    x, y, note = _parse_click_coords_json(
        '{"x": null, "y": null, "reason": "not visible"}'
    )
    assert x is None and y is None and "not visible" in note


def test_parse_float_coords():
    x, y, _ = _parse_click_coords_json('{"x": 99.7, "y": 200.2}')
    assert x == 100 and y == 200


def test_map_image_coords_identity():
    sx, sy, scaled = _map_image_coords_to_screen(100, 50, 1920, 1080, 1920, 1080)
    assert (sx, sy) == (100, 50)
    assert scaled is False


def test_map_image_coords_scaled():
    # Model reports coords on a 960x540 capture; screen is 1920x1080 → 2x scale
    sx, sy, scaled = _map_image_coords_to_screen(78, 87, 960, 540, 1920, 1080)
    assert scaled is True
    assert sx == 156
    assert sy == 174
