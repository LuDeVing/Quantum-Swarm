# Optimistic UI & Reversion Specification

This document maps API state lifecycle to UI visual patterns and provides the "Reversion UX" contract required for the Task MVP.

## 1. State Mapping Table

| API State | UI Pattern | Visual Indicator |
| :--- | :--- | :--- |
| **Pending (Request In-Flight)** | Optimistic Render | Opacity: 0.6, Pointer-events: none |
| **Success (Server OK)** | Resolved | Opacity: 1.0, Border: default |
| **Failure (Reversion)** | Error State | Toast Notification (5s timer), Restore previous list state |

## 2. Reversion UX Contract
If the API returns a 4xx/5xx or timeouts:
1. **Rollback:** Instantly remove the "pending" (0.6 opacity) element from the DOM.
2. **Notification:** Trigger a Toast Notification using `color.error.default`.
3. **Accessibility:** Announce the error to screen readers using `aria-live="assertive"`.

### Toast Component Specification
*   **Role:** `role="alert"`
*   **Props:** `message: string`, `type: 'error' | 'success'`
*   **Trigger:** On Promise.reject() in the `useTaskMutation` hook.
*   **Motion:** `transform: translateY(20px)`, `opacity: 0` -> `opacity: 1`, `duration: 200ms`, `easing: ease-out`.

## 3. Accessibility Requirements
*   **Task List:** Container `<ul>`, each item `<li>`.
*   **Checkboxes:** Must have `aria-label="Mark [Task Title] as [Status]"`.
*   **Delete Button:** Must have `aria-label="Delete [Task Title]"` and `tabindex="0"`.
*   **Focus State:** All interactive elements must show a 2px outline of `color.border.focus` (hex: #3B82F6) on `:focus`.
