# Undo development commands. Every target delegates to scripts/dev.py so the same
# tasks work without make (e.g. Git Bash on Windows):  ./make.sh <target>   or   python scripts/dev.py <target>

PY ?= python
DEV = $(PY) scripts/dev.py

.PHONY: help init install dev backend cli tui gui test test-unit test-integration test-stress \
        lint format typecheck build clean docs

help:
	@echo "Targets: init install dev backend cli tui gui test test-unit test-integration"
	@echo "         test-stress lint format typecheck build clean docs"

init:             ## uv sync, initialise a dev data dir (.dev-home), flutter pub get
	$(DEV) init

install:          ## install the `undo` command for this user (uv tool, editable)
	$(DEV) install

dev: init         ## initialise and run the daemon in the foreground with the dev data dir
	$(DEV) backend

backend:          ## run the daemon in the foreground (UNDO_HOME=.dev-home unless set)
	$(DEV) backend

cli:              ## run the CLI, e.g. make cli ARGS="status"
	$(DEV) cli $(ARGS)

tui:              ## launch the Textual dashboard
	$(DEV) tui

gui:              ## run the Flutter desktop app
	$(DEV) gui

test:             ## unit + integration tests (no stress)
	$(DEV) test

test-unit:
	$(DEV) test-unit

test-integration:
	$(DEV) test-integration

test-stress:
	$(DEV) test-stress

lint:
	$(DEV) lint

format:
	$(DEV) format

typecheck:
	$(DEV) typecheck

build:            ## wheels, desktop bundle and portable archive into dist/
	$(DEV) build

clean:
	$(DEV) clean

docs:             ## regenerate docs/API_OPENAPI.json
	$(DEV) docs
