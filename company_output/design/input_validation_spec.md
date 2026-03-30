# Input Validation Feedback Specification

## Purpose

This document defines the styling and behavior for input validation feedback within the Personal Finance Tracker. It covers valid, invalid, and error states, as well as error message placement and real-time validation.

## Design Tokens

This specification relies on the design tokens defined in `design/design_tokens.md`. Specifically:

*   `error-500`: Color for error messages and invalid input highlighting.
*   `success-500`: Color for valid input highlighting.
*   Font family and size for error messages (inherit from body text).
*   Spacing units for message placement.

## Input States

### Default

*   Input fields have a neutral appearance, as defined in the base component styles.

### Valid

*   **Visual Cue:** A subtle border highlight using `success-500`.
*   **Icon:** A small checkmark icon (SVG) may be displayed within the input field or to the right of it.
*   **Timing:** Validation occurs on blur (when the user leaves the field) and potentially in real-time (on input) for certain fields like amount (numeric validation).

### Invalid

*   **Visual Cue:** A prominent border highlight using `error-500`.
*   **Icon:** A small error icon (SVG) may be displayed within the input field or to the right of it.
*   **Error Message:** A clear and concise error message is displayed below the input field.

## Error Message

*   **Placement:** Immediately below the input field.
*   **Styling:**
    *   Color: `error-500`
    *   Font: Same font family and size as the body text.
    *   Spacing: 4px spacing between the input field and the error message.
*   **Content:**
    *   The error message should be specific and helpful, guiding the user on how to correct the input. Examples:
        *   "Amount must be a number."
        *   "Description cannot be empty."
        *   "Category is required."
        *   "Date must be in YYYY-MM-DD format."

## Real-time Validation

*   **Amount Field:** Validate that the input is a number as the user types. Display an error message immediately if the input is not a number.
*   **Date Field:** Validate the date format (YYYY-MM-DD) as the user types. Provide real-time feedback on the expected format.

## Date Format

*   The date format must be YYYY-MM-DD.
*   Use a date picker component to ensure correct formatting and ease of use.

## Accessibility

*   Use `aria-invalid="true"` on input fields with invalid values.
*   Associate error messages with the input field using `aria-describedby`.
*   Ensure sufficient contrast between the error message text and the background.
