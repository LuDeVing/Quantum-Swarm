## Design Token Set

This document defines the design tokens for the Personal Finance Tracker MVP. These tokens should be used consistently across all components to ensure a unified and cohesive user experience.

### Colors

*   **Primary:**
    *   `primary-50`: `#E3F2FD` - Used for: Subtle backgrounds, input fields.
    *   `primary-100`: `#BBDEFB` - Used for: Hover state of buttons, active state of list items.
    *   `primary-200`: `#90CAF9` - Used for: Border color of input fields.
    *   `primary-500`: `#2196F3` - Used for: Primary button background, link color.
    *   `primary-700`: `#1976D2` - Used for: Primary button hover state background.
    *   **Rationale:** The primary color is a shade of blue, chosen for its association with trust, security, and finance.
*   **Secondary:**
    *   `secondary-50`: `#FAFAFA` - Used for: Background of the entry list.
    *   `secondary-100`: `#F5F5F5` - Used for: Lighter background elements.
    *   `secondary-200`: `#EEEEEE` - Used for: Dividers in the entry list.
    *   `secondary-500`: `#9E9E9E` - Used for: Text color for labels and descriptions.
    *   `secondary-700`: `#616161` - Used for: Disabled button text color.
    *   **Rationale:** The secondary color is a neutral gray, providing a clean and unobtrusive background for the primary content.
*   **Success:**
    *   `success-500`: `#4CAF50` - Used for: Success messages, positive balance display.
    *   **Rationale:** Green is universally associated with success and positive outcomes.
*   **Error:**
    *   `error-500`: `#F44336` - Used for: Error messages, invalid input highlighting.
    *   **Rationale:** Red is universally associated with errors and negative outcomes.
*   **Warning:**
    *   `warning-500`: `#FF9800` - Used for: Warning messages, potentially problematic situations.
    *   **Rationale:** Orange is used to indicate warnings and less critical errors.
*   **Info:**
    *   `info-500`: `#29B6F6` - Used for: Information messages and neutral announcements.
    *   **Rationale:** Light blue is used for informative messages.

### Typography

*   **Font Family:**
    *   `font-family-base`: `Roboto, sans-serif` - Used for: All text elements.
    *   **Rationale:** Roboto is a clean and modern sans-serif font that is easy to read and widely available.
*   **Font Sizes:**
    *   `font-size-xs`: `0.75rem` (12px) - Used for: Error messages, small labels.
    *   `font-size-sm`: `0.875rem` (14px) - Used for: Input fields, body text.
    *   `font-size-md`: `1rem` (16px) - Used for: Section titles, larger text elements.
    *   `font-size-lg`: `1.125rem` (18px) - Used for: Main headings.
    *   `font-size-xl`: `1.25rem` (20px) - Used for: Large headings.
    *   **Rationale:** A clear and consistent font size scale ensures readability and visual hierarchy.
*   **Font Weights:**
    *   `font-weight-light`: `300`
    *   `font-weight-regular`: `400`
    *   `font-weight-medium`: `500`
    *   `font-weight-bold`: `700`
    *   **Rationale:** Provides emphasis and visual structure.

### Spacing

*   `spacing-2`: `0.125rem` (2px)
*   `spacing-4`: `0.25rem` (4px)
*   `spacing-8`: `0.5rem` (8px)
*   `spacing-12`: `0.75rem` (12px)
*   `spacing-16`: `1rem` (16px)
*   `spacing-20`: `1.25rem` (20px)
*   `spacing-24`: `1.5rem` (24px)
*   `spacing-32`: `2rem` (32px)
*   **Rationale:** A consistent spacing scale ensures visual rhythm and balance.

### Border Radius

*   `border-radius-sm`: `0.25rem` (4px) - Used for: Input fields, buttons.
*   `border-radius-md`: `0.5rem` (8px) - Used for: Cards, larger elements.
*   `border-radius-lg`: `0.75rem` (12px) - Used for: Modal windows.
*   **Rationale:** Defines the roundness of corners for a softer, more modern look.

### Shadows

*   `shadow-sm`: `0 1px 2px 0 rgba(0, 0, 0, 0.05)` - Used for: Subtle highlights, active states.
*   `shadow-md`: `0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)` - Used for: Card elevation.
*   `shadow-lg`: `0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)` - Used for: Modal windows, prominent elements.
*   **Rationale:** Adds depth and visual hierarchy to the interface.

### Icons

*   **Style:** Material Design Icons (filled)
*   **Size:** 24x24 px
*   **Color:** Determined by context (primary, secondary, success, error, etc.)
*   **Examples:**
    *   Checkmark (Success)
    *   Exclamation point (Warning)
    *   Close (Dismissible alerts)
    *   Info (Information)
    *   Add (New entry)
    *   Edit (Edit entry)
    *   Delete (Delete entry)
    *   Filter (Category filter)
    *   **Rationale:** Provides visual cues and enhances usability. Using a consistent icon set maintains a unified look and feel.
