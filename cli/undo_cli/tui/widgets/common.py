"""Reusable TUI widgets: stat cards, a data pane base class and modal dialogs."""

from __future__ import annotations

from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static
from undo_core.utils.errors import UndoError


class StatCard(Static):
    DEFAULT_CSS = """
    StatCard {
        width: 1fr;
        height: 5;
        border: round $primary-background-lighten-2;
        padding: 0 1;
        content-align: left middle;
    }
    """

    def __init__(self, title: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.title = title
        self.set_value("…")

    def set_value(self, value: str, note: str = "") -> None:
        self.update(
            f"[dim]{self.title}[/dim]\n[bold]{value}[/bold]"
            + (f"\n[dim]{note}[/dim]" if note else "")
        )


class DataPane(Vertical):
    """A pane that loads data in a worker thread and renders it on the UI thread."""

    DEFAULT_CSS = """
    DataPane { height: 1fr; }
    DataPane .pane-status { height: 1; color: $text-muted; }
    """

    def fetch(self) -> Any:
        raise NotImplementedError

    def show(self, data: Any) -> None:
        raise NotImplementedError

    @property
    def backend(self) -> Any:
        return self.app.backend  # type: ignore[attr-defined]

    def on_mount(self) -> None:
        self.reload()

    @work(thread=True, exclusive=True, group="pane-load")
    def reload(self) -> None:
        try:
            data = self.fetch()
        except UndoError as exc:
            self.app.call_from_thread(self.app.notify, exc.message, severity="error", title="Error")
            return
        except Exception as exc:
            self.app.call_from_thread(
                self.app.notify, str(exc), severity="error", title="Unexpected error"
            )
            return
        self.app.call_from_thread(self.show, data)


class ConfirmModal(ModalScreen[bool]):
    DEFAULT_CSS = """
    ConfirmModal { align: center middle; }
    ConfirmModal > Vertical { width: 70; height: auto; border: thick $warning; background: $surface; padding: 1 2; }
    ConfirmModal Horizontal { height: auto; margin-top: 1; align-horizontal: right; }
    ConfirmModal Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self, message: str, confirm_label: str = "Confirm", variant: str = "warning"
    ) -> None:
        super().__init__()
        self.message = message
        self.confirm_label = confirm_label
        self.variant = variant

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.message)
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button(self.confirm_label, id="ok", variant=self.variant)  # type: ignore[arg-type]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)


class PromptModal(ModalScreen[dict[str, str] | None]):
    """Ask for one or more text values."""

    DEFAULT_CSS = """
    PromptModal { align: center middle; }
    PromptModal > Vertical { width: 80; height: auto; border: thick $primary; background: $surface; padding: 1 2; }
    PromptModal Input { margin-bottom: 1; }
    PromptModal Horizontal { height: auto; align-horizontal: right; }
    PromptModal Button { margin-left: 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self, title: str, fields: list[tuple[str, str, str]], ok_label: str = "OK"
    ) -> None:
        """fields: (key, label, default)."""
        super().__init__()
        self.title_text = title
        self.fields = fields
        self.ok_label = ok_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"[bold]{self.title_text}[/bold]")
            for key, label, default in self.fields:
                yield Label(label)
                yield Input(value=default, id=f"f-{key}")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button(self.ok_label, id="ok", variant="primary")

    def _values(self) -> dict[str, str]:
        return {key: self.query_one(f"#f-{key}", Input).value for key, _l, _d in self.fields}

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self._values() if event.button.id == "ok" else None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self.dismiss(self._values())

    def action_cancel(self) -> None:
        self.dismiss(None)
