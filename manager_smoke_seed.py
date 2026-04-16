"""Seeded wx GUI + ``design/agent_test_hints.md`` for ``run_manager_stage_smoke`` (importable without API keys).

Uses wxPython (native Win32 controls) so Windows UIA exposes real ButtonControl / EditControl
elements with names — enabling the OpenClaw-style Snapshot→Ref→Click→ReadText loop without
any vision API calls.
"""

from __future__ import annotations

from pathlib import Path


def write_smoke_agent_test_hints(project_root: Path) -> None:
    """FEATURE/FIND/TEST for the seeded wx app — manager reads via ``design/agent_test_hints.md``."""
    design = project_root / "design"
    design.mkdir(parents=True, exist_ok=True)
    (design / "agent_test_hints.md").write_text(
        "# Manager smoke GUI — verify these on the running app\n\n"
        "FEATURE: Single-window wx demo: text entry, Show button copies entry text into a result label.\n"
        "FIND: Window title contains `Smoke GUI`. Controls exposed via Windows UIA:\n"
        "  - EditControl  named 'Entry'  (pre-filled 'type here')\n"
        "  - ButtonControl named 'Show'\n"
        "  - StaticText / TextControl named 'Result' (updates when Show is clicked)\n\n"
        "NOTE: This app uses wxPython — native Win32 controls. UIA is fully supported.\n"
        "Use the OpenClaw Snapshot→Ref→Click→ReadText loop (NO screenshots needed for locate/verify):\n\n"
        "TEST:\n"
        "(1) desktop_list_windows() → desktop_activate_window('Smoke GUI') to focus.\n"
        "(2) SNAPSHOT: desktop_uia_list_elements('Smoke GUI') — confirm EditControl 'Entry' and ButtonControl 'Show' appear.\n"
        "(3) ACT on Entry: desktop_uia_click('Smoke GUI', 'Entry') to focus the field.\n"
        "(4) desktop_keyboard('hotkey', 'ctrl', 'a') then desktop_keyboard('type', text='hello smoke').\n"
        "(5) ACT on Show: desktop_uia_click('Smoke GUI', 'Show') — click by name, no coordinates needed.\n"
        "(6) VERIFY: desktop_uia_read_text('Smoke GUI') — confirm 'hello smoke' appears in the Result label.\n"
        "    Only take a desktop_screenshot if desktop_uia_read_text returns empty or unclear.\n"
        "Always check the uia_list_elements output before clicking — if a control is missing, "
        "the app may not have launched yet.\n",
        encoding="utf-8",
    )


def seed_minimal_gui_project(code_dir: Path) -> None:
    """wx Entry+Show app + passing pytest — native Win32 controls expose full UIA accessibility."""
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "main.py").write_text(
        '''\
"""wx smoke app — Entry + Show updates a label via native Win32 controls (UIA-accessible).

Controls exposed to Windows UIA:
  EditControl   name="Entry"   (text input, pre-filled 'type here')
  ButtonControl name="Show"    (copies Entry text to Result label)
  TextControl   name="Result"  (result label, updates on Show click)

See design/agent_test_hints.md for the OpenClaw-style test sequence.
"""
import wx


class SmokeFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title="Smoke GUI", size=(420, 300))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        instructions = wx.StaticText(
            panel,
            label="Type in the field, click Show — the text below must match the field.",
        )
        instructions.Wrap(390)

        # StaticText label before TextCtrl lets UIA infer accessible name "Entry"
        entry_lbl = wx.StaticText(panel, label="Entry")
        self.entry = wx.TextCtrl(panel, value="type here", name="Entry")

        self.result = wx.StaticText(panel, label="(result appears here)", name="Result")
        self.result.SetForegroundColour(wx.Colour(102, 102, 102))

        show_btn = wx.Button(panel, label="Show", name="Show")
        show_btn.Bind(wx.EVT_BUTTON, self._on_show)

        sizer.Add(instructions, 0, wx.ALL | wx.CENTER, 10)
        sizer.Add(entry_lbl, 0, wx.LEFT | wx.TOP, 8)
        sizer.Add(self.entry, 0, wx.ALL | wx.EXPAND, 6)
        sizer.Add(self.result, 0, wx.ALL | wx.CENTER, 8)
        sizer.Add(show_btn, 0, wx.ALL | wx.CENTER, 6)
        panel.SetSizer(sizer)
        self.Centre()

        # Auto-close after 2 minutes so it never blocks CI
        wx.CallLater(120_000, self.Close)

    def _on_show(self, _event: wx.CommandEvent) -> None:
        t = self.entry.GetValue()
        self.result.SetLabel(t if t else "(empty)")
        self.result.SetForegroundColour(wx.BLACK)
        self.result.GetParent().Layout()


def main() -> None:
    app = wx.App(False)
    frame = SmokeFrame()
    frame.Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    (code_dir / "app").mkdir(exist_ok=True)
    (code_dir / "app" / "__init__.py").write_text("", encoding="utf-8")
    tests = code_dir / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )
    (tests / "__init__.py").write_text("", encoding="utf-8")


if __name__ == "__main__":
    import sys

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("manager_smoke_output")
    code = out / "code"
    seed_minimal_gui_project(code)
    write_smoke_agent_test_hints(out)
    print(f"Seeded smoke project → {out.resolve()}")
    print(f"  code/main.py     — wx Entry+Show app (native UIA controls)")
    print(f"  design/agent_test_hints.md — OpenClaw Snapshot→Ref→Click→ReadText checklist")
