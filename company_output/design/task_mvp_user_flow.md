# User Journey: Task Management MVP

## Core Goal
Provide a seamless, high-performance interface for managing tasks, utilizing an Optimistic UI strategy to ensure perceived zero-latency interaction.

## 1. User Flows

### A. Task Lifecycle
1.  **Entry Point:** User opens the app.
    *   *Empty State:* Display empty illustration + "Add your first task" call-to-action (CTA).
    *   *List State:* Display existing tasks in a scrollable list.
2.  **Creation:**
    *   User focuses on the "New Task" input at the top of the list.
    *   User types title (1-100 chars) and presses "Enter" or clicks "Add".
    *   **Optimistic Action:** Row instantly appears in list with 50% opacity.
    *   **Backend Sync:** Request sent to `POST /tasks`.
    *   **Success:** Row transitions to 100% opacity.
    *   **Error:** Row slides out (reversion), Toast error appears, input remains focused with previous text intact.
3.  **Completion/Toggle:**
    *   User clicks the checkbox/toggle.
    *   **Optimistic Action:** Status updates immediately (visual strike-through).
    *   **Backend Sync:** Request sent to `PUT /tasks/:id`.
    *   **Error:** Status reverts, Toast error appears.
4.  **Deletion:**
    *   User clicks "Delete" icon.
    *   **Optimistic Action:** Row disappears immediately.
    *   **Backend Sync:** Request sent to `DELETE /tasks/:id`.
    *   **Error:** Row reappears, Toast error appears.

## 2. Error Recovery Protocol
When an optimistic action fails, we do not lock the interface.
- **Visuals:** The specific row reverts to its previous state.
- **Messaging:** A global error toast appears at the bottom-center (duration: 5000ms).
- **Data Integrity:** The input field restores the content of the failed creation to prevent data loss.

## 3. Interaction Specs
- **Click Targets:** Minimum 44x44px.
- **Animations:** 200ms ease-out transitions for opacity and list reordering.
- **Keyboard:** `Enter` triggers submission; `Esc` clears input focus.
