# Manager smoke GUI — verify these on the running app

FEATURE: Single-window wx demo: text entry, Show button copies entry text into a result label.
FIND: Window title contains `Smoke GUI`. Controls exposed via Windows UIA:
  - EditControl  named 'Entry'  (pre-filled 'type here')
  - ButtonControl named 'Show'
  - StaticText / TextControl named 'Result' (updates when Show is clicked)

NOTE: This app uses wxPython — native Win32 controls. UIA is fully supported.
Use the OpenClaw Snapshot→Ref→Click→ReadText loop (NO screenshots needed for locate/verify):

TEST:
(1) desktop_list_windows() → desktop_activate_window('Smoke GUI') to focus.
(2) SNAPSHOT: desktop_uia_list_elements('Smoke GUI') — confirm EditControl 'Entry' and ButtonControl 'Show' appear.
(3) ACT on Entry: desktop_uia_click('Smoke GUI', 'Entry') to focus the field.
(4) desktop_keyboard('hotkey', 'ctrl', 'a') then desktop_keyboard('type', text='hello smoke').
(5) ACT on Show: desktop_uia_click('Smoke GUI', 'Show') — click by name, no coordinates needed.
(6) VERIFY: desktop_uia_read_text('Smoke GUI') — confirm 'hello smoke' appears in the Result label.
    Only take a desktop_screenshot if desktop_uia_read_text returns empty or unclear.
Always check the uia_list_elements output before clicking — if a control is missing, the app may not have launched yet.
