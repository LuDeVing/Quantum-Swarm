# Component Specifications: States & Interactions

This file defines the interaction states required by engineering to implement the Task MVP components.

## 1. Interaction States (Visual)
- **Primary Button**
  - `Default`: #0070F3, Text: #FFFFFF, Padding: 8px 16px, Border-Radius: 6px
  - `Hover`: background-color: #0060D9, transition: 200ms ease-out
  - `Active`: scale: 0.98, transition: 100ms
  - `Disabled`: #EAEAEA, Text: #999, Cursor: not-allowed
  - `Loading`: Spinner icon + disabled state

- **Task Card**
  - `Default`: background: #FFFFFF, border: 1px solid #EAEAEA, padding: 12px
  - `Optimistic`: opacity: 0.6, cursor: wait
  - `Completed`: text: #999, text-decoration: line-through

- **Input Field**
  - `Focus`: border: 1px solid #0070F3, outline: 0
  - `Error`: border: 1px solid #E00, background-color: rgba(224, 0, 0, 0.05)

## 2. Animation Specs
- **Transitions:** 200ms ease-out for all color/state changes.
- **Loading State:** Spinner animation 360deg linear infinite over 1s.
- **Reversion (Error):** Shake animation (transform: translateX(-5px)) on field if validation fails.

## 3. Accessibility
- All buttons must have `aria-label` when no visible text is present.
- Error states must use `aria-invalid="true"` and a descriptive `aria-describedby` link to an error message node.
- Focus rings must be visible.
