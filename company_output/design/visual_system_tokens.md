# Visual System & Motion Tokens

This document extends the core `ui-system-specs.md` with explicit **Motion Tokens** and **Accessibility** requirements for all UI components.

## 1. Motion Tokens
All state transitions must use these tokens to ensure consistent, responsive "Optimistic UI" feedback.

| Token | Value | Purpose |
|-------|-------|---------|
| `motion.duration.fast` | 150ms | Hover, toggle, micro-interactions |
| `motion.duration.base` | 200ms | Optimistic state transitions |
| `motion.ease.default` | `cubic-bezier(0.4, 0, 0.2, 1)` | Standard UI movement |

*   **Implementation Note:** When an optimistic task is created, the list item must fade in (opacity 0 to 1) over `motion.duration.base` using `motion.ease.default`. If a reversion occurs, the item must "shake" (x-axis offset 4px) for 100ms before removing.

## 2. Accessibility (A11y) Standards
Every component must adhere to these standards:

- **Keyboard Navigation:** All interactive elements (`Button`, `Checkbox`, `DeleteAction`) must be reachable via `Tab` and triggered via `Enter` or `Space`.
- **Focus States:** Every component must have a visible `focus` state using `border.focus` (2px solid #3B82F6).
- **Labels:** 
    - `DeleteAction` icons must have `aria-label="Delete task"`.
    - `StatusToggle` checkboxes must have `aria-label="Toggle task status"`.
- **Error States:** Errors must be surfaced via `aria-live="polite"` containers so screen readers announce the reversion message immediately.

## 3. Optimistic Visual States
Map for engineering to correlate state with visual token properties.

| API State | Visual Pattern | Token Reference |
|-----------|----------------|-----------------|
| **Pending** | Opacity 0.6 | N/A (Opacity prop) |
| **Success** | Opacity 1.0 | N/A |
| **Reversion** | Red border + Shake | `border.error` |

## 4. Design-to-Code Handoff
UI Designers and Developers: Ensure all CSS/Tailwind configs map exactly to the Spacing, Color, and Motion tables defined here. 
- Use `spacing.sm` (8px) for internal component padding.
- Use `spacing.md` (16px) for layout margins between `TaskItem` rows.
