# Component Library Specification (v2.0)

This specification integrates the UI token system, formalizes interaction states, and defines accessibility requirements for the Task MVP.

## 1. Interaction States & Token Mapping
All components must map visual properties to the `ui-system-specs.md` token set.

### Button (Primary & Secondary)
- **Default**: `bg: color.brand.primary.default`, `text: color.text.white`
- **Hover**: `bg: color.brand.primary.hover`
- **Active**: `bg: color.brand.primary.active`
- **Disabled**: `opacity: 0.5`, `cursor: not-allowed`
- **Focus**: `outline: 2px solid color.brand.focus`, `outline-offset: 2px`

### Task Item (List)
- **Pending (Optimistic)**: `opacity: 0.6`, `cursor: wait`
- **Default**: `bg: color.background.secondary`, `border: 1px solid color.border.default`
- **Hover**: `bg: color.background.primary`
- **Focus**: `outline: 2px solid color.brand.focus`

## 2. Accessibility (WCAG 2.1 AA)
- **Keyboard Navigation**: All interactive elements (Add button, Checkbox, Delete icon) must be focusable via `Tab`.
- **Focus Order**: Input → Add Button → Task List (Top to Bottom).
- **ARIA Roles**:
  - `Task Item`: `role="listitem"`
  - `Add Button`: `aria-label="Add new task"`
  - `Delete Button`: `aria-label="Delete task: [Task Title]"`
  - `Checkbox`: `aria-label="Toggle completion status for: [Task Title]"`

## 3. Motion Tokens (Referencing visual design)
- **Transition Duration**: `motion.duration.fast = 200ms`
- **Easing**: `motion.ease.out = cubic-bezier(0.4, 0, 0.2, 1)`

## 4. Error State Implementation
If an API request fails during an optimistic update:
1. **Reversion**: The specific item reverts to its previous state (e.g., checkbox unchecks).
2. **Notification**: A Toast component appears at the bottom-right (fixed position).
   - `bg: color.error.default`, `text: color.text.white`
   - `duration`: 5000ms.
   - `accessibility`: `role="alert"`.
