# Master Handoff Manifest: Task MVP

This document synthesizes all design specifications into a unified reference for Engineering.

## 1. Core Principles
- **Contract-First:** All API interactions must follow the `packages/contracts` schema.
- **Optimistic UI:** Immediate UI updates, robust error reversion (see `design/ux_error_onboarding_protocol.md`).
- **Performance:** Transitions use `200ms ease-in-out`.

## 2. Design Tokens & Semantic Mapping
| Semantic Token | Visual Value | Use Case |
| :--- | :--- | :--- |
| `Action-Primary-Bg` | `#3B82F6` | Primary Buttons |
| `Action-Primary-Hover` | `#2563EB` | Button Hover |
| `Action-Primary-Focus` | `#60A5FA` | Focus Outline |
| `Status-Pending` | `#F59E0B` | Pending Tasks |
| `Status-Completed` | `#10B981` | Completed Tasks |
| `Text-Primary` | `#1E293B` | Task Labels |
| `Border-Default` | `#E2E8F0` | Input/Component Borders |

## 3. Interaction Patterns
- **Buttons:** 
    - Default: `bg-3B82F6`
    - Hover: `bg-2563EB`
    - Focus: `outline: 2px solid #60A5FA`
- **Inputs:** 
    - Focused state must trigger a 1px border transition using `Action-Primary-Focus`.
- **List Items:** 
    - Hover: `bg-F1F5F9`

## 4. Layout
- **Container:** Max-width `800px`, centered.
- **Breakpoints:** 
    - Mobile: `< 768px` (Full bleed)
    - Desktop: `>= 768px` (Containerized)

## 5. Engineering Action Plan
1. Implement `Toast` component (Top-Right, Fixed).
2. Apply `transition-duration-200` to all task list item state changes.
3. Use the provided `Semantic Tokens` in all Tailwind classes.
4. Ensure `docker-compose` lifecycle triggers full environment bootstrap.

---
**Status:** Design finalized for Engineering handoff. All previous conflicts regarding naming (`spacing-md` vs `md-spacing`) are reconciled as `md` (16px).
