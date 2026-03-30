## Error Alert Component Specification

### Purpose

To display error, warning, success, and information messages to the user in a consistent and accessible manner.

### Props/Inputs

*   `type`: `string` (required) - The type of alert to display. Possible values: `success`, `warning`, `error`, `info`.
*   `message`: `string` (required) - The message to display in the alert.
*   `isDismissible`: `boolean` (optional) - Whether the alert can be dismissed by the user. Default: `false`.
*   `aria-label`: `string` (optional) - An ARIA label for the alert, providing a descriptive name for screen readers.

### Visual States

*   **Default:**
    *   Background color: Determined by the `type` prop (see below).
    *   Text color: Determined by the `type` prop (see below).
    *   Icon: Determined by the `type` prop (see below).
*   **Hover (if `isDismissible` is `true`):**
    *   Background color: Slightly darker shade of the default background color.
    *   Close button color: Darker shade of the default text color.
*   **Active (if `isDismissible` is `true`):**
    *   Background color: Even darker shade of the default background color.
    *   Close button color: Even darker shade of the default text color.

### Visual Specification

*   **Container:**
    *   Padding: `spacing-16`
    *   Border radius: `radius-md`
    *   Font family: `Arial, sans-serif`
    *   Font size: `text-sm`
*   **Message:**
    *   Margin left: `spacing-8` (to accommodate the icon)
*   **Close Button (if `isDismissible` is `true`):**
    *   Position: Absolute, top right
    *   Padding: `spacing-4`
    *   Cursor: Pointer

### Type-Specific Styling

*   **Success:**
    *   Background color: `success-500`
    *   Text color: `secondary-50`
    *   Icon: Checkmark (Font Awesome or similar)
*   **Warning:**
    *   Background color: `warning-500`
    *   Text color: `secondary-700`
    *   Icon: Exclamation point (Font Awesome or similar)
*   **Error:**
    *   Background color: `error-500`
    *   Text color: `secondary-50`
    *   Icon: X Mark (Font Awesome or similar)
*   **Info:**
    *   Background color: `info-500`
    *   Text color: `secondary-700`
    *   Icon: Information Circle (Font Awesome or similar)

### Interaction Behavior

*   If `isDismissible` is `true`, the alert should be dismissed when the user clicks the close button.
*   The alert should be keyboard-navigable. The close button should be focusable and accessible via the Tab key.

### Accessibility

*   Use the `aria-label` prop to provide a descriptive name for screen readers.
*   Ensure sufficient contrast between the background and text colors.
*   Use appropriate ARIA attributes to indicate the alert's type and status.

