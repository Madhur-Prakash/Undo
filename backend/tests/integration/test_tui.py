"""Headless Textual TUI test: every tab renders real backend data and key actions work."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from helpers import write
from textual.widgets import Checkbox, DataTable, Select, TabbedContent
from undo_cli.commands.common import State
from undo_cli.tui.app import UndoTUI
from undo_core.service import UndoService
from undo_core.versioning.capture import RootRef

pytestmark = pytest.mark.integration


def test_tui_tabs_and_file_history(service: UndoService, tracked: RootRef) -> None:
    write(tracked.path / "hello.txt", "v1")
    service.scan()
    write(tracked.path / "hello.txt", "v2")
    write(tracked.path / "big.txt", "x" * 100)
    service.scan()
    service.create_snapshot(name="tui-snap", root=tracked.id)
    data_dir = str(service.ctx.paths.data_dir)

    async def scenario() -> None:
        app = UndoTUI(State(data_dir=data_dir, local_only=True))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause(0.5)
            tabs = app.query_one(TabbedContent)
            for key, tab in zip(
                "1234567",
                ["dashboard", "roots", "files", "history", "snapshots", "storage", "settings"],
                strict=True,
            ):
                await pilot.press(key)
                await pilot.pause(0.4)
                assert tabs.active == tab
            await pilot.press("3")
            await pilot.pause(0.6)
            files = app.query_one("#pane-files").query_one(DataTable)
            assert files.row_count == 2
            assert files.get_row_at(0)[1].endswith("hello.txt")
            app.query_one("#pane-files").query_one("#sort-key", Select).value = "size"
            await pilot.pause(0.6)
            assert files.get_row_at(0)[1].endswith("big.txt")  # largest first
            app.query_one("#pane-files").query_one("#sort-reverse", Checkbox).value = True
            await pilot.pause(0.6)
            assert files.get_row_at(0)[1].endswith("hello.txt")
            app.query_one("#pane-files").query_one("#sort-key", Select).value = "path"
            await pilot.pause(0.6)
            assert files.get_row_at(0)[1].endswith("hello.txt")  # Z to A: hello before big
            files.move_cursor(row=0)
            files.focus()
            await pilot.press("enter")
            await pilot.pause(0.8)
            history = app.screen.query_one(DataTable)
            assert history.row_count == 2  # MODIFY + CREATE
            await pilot.press("escape")
            await pilot.press("5")
            await pilot.pause(0.6)
            snaps = app.query_one("#pane-snapshots").query_one(DataTable)
            assert snaps.row_count == 1
            await pilot.press("4")
            await pilot.pause(0.6)
            log = app.query_one("#pane-history").query_one(DataTable)
            assert log.row_count == 3
            app.query_one("#pane-history").query_one("#sort-key", Select).value = "path"
            await pilot.pause(0.4)
            assert log.get_row_at(0)[5].endswith("big.txt")
            await pilot.press("q")

    asyncio.run(scenario())
    assert Path(data_dir).exists()
