## Input Validation Feedback Specification

### Purpose

To provide clear, immediate, and accessible feedback to users regarding the validity of their input in the personal finance tracker.

### Props/Inputs

*   `isValid`: `boolean` - Indicates whether the input is currently valid.
*   `errorMessage`: `string` - The error message to display when the input is invalid. This prop is only relevant when `isValid` is `false`.
*   `aria-describedby`: `string` - Associates the error message with the input field for accessibility purposes. Should match the `id` of the error message element.

### Visual States

*   **Default (Valid):**
    *   Input field:
        *   Border color: `primary-200`
    *   Error message:
        *   Hidden.
*   **Focus (Valid):**
    *   Input field:
        *   Border color: `primary-500`
        *   Shadow: `shadow-sm`
    *   Error message:
        *   Hidden.
*   **Invalid:**
    *   Input field:
        *   Border color: `error-500`
    *   Error message:
        *   Visible.
        *   Color: `error-500`
        *   Font size: `font-size-sm`
        *   Margin top: `spacing-4`
*   **Disabled:**
    *   Input field:
        *   Background color: `secondary-100`
        *   Border color: `secondary-200`
        *   Text color: `secondary-500`
    *   Error message:
        *   Hidden.

### Visual Specification

*   **Input Field:**
    *   Font family: `font-family-base`
    *   Font size: `font-size-sm`
    *   Padding: `spacing-8` `spacing-12`
    *   Border: `1px solid`
    *   Border radius: `border-radius-sm`
*   **Error Message:**
    *   Font family: `font-family-base`
    *   Font size: `font-size-xs`
    *   Color: `error-500`
    *   Margin top: `spacing-4`

### Accessibility

*   When the input is invalid, the error message should be associated with the input field using the `aria-describedby` attribute. This allows screen readers to announce the error message when the input field is focused.
*   Ensure sufficient contrast between the error message text and the background.
*   Use semantic HTML for the error message (e.g., `<p>` or `<div>` with appropriate ARIA attributes).

### Interaction Behavior

*   **Real-time Validation:** Validate the input as the user types. Provide immediate feedback on the validity of the input.
*   **Error Message Display:** Display the error message below the input field when the input is invalid.
*   **Focus Management:** When an error occurs, ensure that the focus remains on the input field so that the user can correct the error.
