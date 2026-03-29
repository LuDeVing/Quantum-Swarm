As Design Manager, I have synthesized the outputs from the Research, UI, and Visual teams into the **Quantum Swarm Design System Specification (Sprint 1)**. This document is the source of truth for all frontend implementation. Engineering, adhere strictly to these token values and state logic.

---

# Design System Specification: Task MVP (Sprint 1)

## 1. Foundation: Atomic Token System (`tokens.json`)
All components must reference these semantic tokens. **No hardcoded hex or pixel values in CSS/Styled-Components.**

*   **Color Palette (Semantic):**
    *   `bg-primary`: #FFFFFF, `bg-surface`: #F8F9FA, `bg-error`: #FEE2E2
    *   `text-main`: #111827, `text-muted`: #6B7280, `text-error`: #991B1B
    *   `brand-primary`: #2563EB, `brand-hover`: #1D4ED8
    *   `status-pending`: #D97706, `status-completed`: #059669
*   **Spacing (4px base grid):**
    *   `xs`: 4px, `sm`: 8px, `md`: 16px, `lg`: 24px, `xl`: 32px
*   **Typography:**
    *   `family-body`: 'Inter', sans-serif; `family-mono`: 'JetBrains Mono', monospace
    *   `size-base`: 16px, `weight-bold`: 600
*   **Motion:** `transition-ease`: "cubic-bezier(0.4, 0, 0.2, 1)", `duration-fast`: "150ms"

## 2. Component Inventory & Specs
| Component | Props | Interaction / Behavior |
| :--- | :--- | :--- |
| **TaskInput** | `onSubmit: (t: string) => void` | Triggers Optimistic UI. Disable input during `isSubmitting`. |
| **TaskCard** | `task: Task, onToggle: (id: string) => void` | Height: 56px. Border: 1px `brand-primary` on focus. |
| **StatusBadge** | `status: 'PENDING' \| 'COMPLETED'` | Background opacity 10% of status color. |
| **Toast** | `type: 'error' \| 'success', msg: string` | Auto-dismiss after 3000ms. Fixed position: `bottom-right`. |

## 3. Optimistic UI & Error Handling (UX Spec)
To prevent "jank" while maintaining data integrity, we follow these interaction rules:

1.  **Creation Flow:**
    *   **User Action:** User hits "Add".
    *   **UI Response:** Append item with `id: temp_id` and `status: PENDING` immediately. Opacity 0.6 (visual cue for "Syncing").
    *   **API Success:** Replace `temp_id` with real `UUID` from server. Opacity 1.0.
    *   **API Failure:** Remove item immediately. Trigger `Toast` (Error: "Failed to create task").
2.  **Toggle Flow:**
    *   **UI Response:** Flip checkbox icon immediately.
    *   **API Failure:** Revert checkbox to previous state. Trigger `Toast` (Error: "Sync failed. Reverting...").

## 4. Implementation Guidelines for Engineering
*   **Responsive Breakpoint:** Mobile-first. Max-width 640px for the container. Use `md` spacing between `TaskCards`.
*   **Accessibility:** 
    *   Every `TaskCard` action must be keyboard navigable (`Tab` + `Enter`). 
    *   Contrast ratios must meet WCAG 2.1 AA (4.5:1 minimum for text).
    *   Buttons must have an `aria-label` (e.g., "Delete task: [Task Title]").
*   **Request Queue:** Use `src/services/requestQueue.ts` to ensure mutations are executed in serial. Do not allow overlapping network requests for the same `Task ID`.

## 5. Critical Path Priority
1.  **P0 (Mandatory for Friday):** `TaskInput` + `TaskCard` (optimistic CRUD), Error Toast, `GET /tasks` reconciliation.
2.  **P1 (Deferred):** Empty State illustrations, advanced animation sequences (staggered lists), custom scrollbars.

**Managerial Review:** This specification resolves the conflict between UI responsiveness and data integrity by mandating server-side reconciliation via the `full Task object` return pattern defined in the API contract. **Engineering, you are cleared to proceed with implementation.** If the API contract changes, notify me immediately; do not alter component props until the `packages/contracts` schema is updated.