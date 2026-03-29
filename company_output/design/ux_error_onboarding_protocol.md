# UX/UI Error Recovery & Onboarding Protocol

This document serves as the authoritative guide for error handling and zero-state UX for the Task MVP.

## 1. Error Recovery Protocol (Optimistic UI)

When an optimistic action (Create, Toggle, Delete) fails, the UI must provide clear feedback and enable recovery without data loss.

| Failure Trigger | UI Response | Recovery Action |
| :--- | :--- | :--- |
| **Network Timeout** | Opacity 1.0 (Reset), Toast: "Connection lost. Retrying..." | Auto-retry x3 then show "Retry" button. |
| **401 Unauthorized** | Toast: "Session expired. Please refresh." | Force redirect to login or show login modal. |
| **422 Validation Error** | Toast: "Invalid task data." | Highlight invalid input; retain typed content. |
| **500 Server Error** | Toast: "Service unavailable." | Revert UI state; offer "Retry" action. |

### Motion Tokens for Transitions
- **Duration:** `200ms`
- **Easing:** `cubic-bezier(0.4, 0, 0.2, 1)` (standard deceleration)

## 2. Onboarding & Zero State

The "Zero State" is the entry point for new users.

### Zero State View
- **Empty Illustration:** Minimal SVG icon (e.g., a checkmark box).
- **Text:** "No tasks yet. Stay organized!"
- **Call-to-Action:** Large primary button: "Create your first task".
- **Interaction:** Clicking the button auto-focuses the input field at the top of the list.

## 3. Responsive Breakpoints

To ensure consistency across devices, use these standardized breakpoints.

| Device | Width | Grid/Layout |
| :--- | :--- | :--- |
| Mobile | < 768px | Single column, full-width inputs |
| Desktop | >= 768px | Max-width 800px, centered container |

---
**Implementation Note:** All error messages must be rendered via a centralized Toast component to prevent UI clutter and ensure consistent placement (Top-Right, Fixed).
