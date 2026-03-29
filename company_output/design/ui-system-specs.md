# Atomic Design Tokens & UX Specifications

## Overview
This document defines the core visual tokens and error-handling UX patterns for the Task MVP. These tokens must be used by all UI components to ensure consistency.

## 1. Visual Tokens (JSON)

```json
{
  "colors": {
    "brand": { "primary": "#3B82F6", "hover": "#2563EB" },
    "ui": { "bg": "#F8FAFC", "surface": "#FFFFFF", "border": "#E2E8F0" },
    "text": { "primary": "#1E293B", "secondary": "#64748B", "error": "#B91C1C" },
    "status": { "completed": "#10B981", "pending": "#F59E0B" }
  },
  "spacing": { "xs": "4px", "sm": "8px", "md": "16px", "lg": "24px", "xl": "32px" },
  "radius": { "sm": "4px", "md": "8px" },
  "transitions": { "fast": "150ms ease-in-out", "default": "200ms ease-out" }
}
```

## 2. Optimistic UI: Loading & Error Patterns

To maintain a responsive experience while respecting the network reality, the following states are mandated:

### Optimistic Transition
- **Trigger:** User clicks "Add Task" or "Toggle Status".
- **Visual:** Immediate UI update (e.g., checkbox toggles to checked, task appears in list) with 30% opacity overlay on the specific element to indicate pending sync.

### Error Reversion
- **Trigger:** API returns an error (4xx/5xx).
- **Behavior:**
    1.  **Immediate Reversion:** The specific task reverts to its previous state (e.g., checkbox unchecks).
    2.  **Notification:** An error toast appears in the top-right corner (fixed positioning).
- **Toast Specification:**
    - Background: `#FEF2F2` (Red 50)
    - Border: `1px solid #EF4444`
    - Text: `Color: #B91C1C`, `Font: Inter, 14px, Bold`
    - Icon: Error Alert Icon
    - Duration: Auto-dismiss after 5s or manual close.

## 3. Implementation Handoff
- **Animations:** All state changes must use `200ms ease-out`.
- **Accessibility:** All interactive elements must have a `focus` state: `2px solid #3B82F6` with `2px offset`.
- **Responsiveness:** Components must be fluid. Container width: Max 800px on desktop, 100% on mobile.
