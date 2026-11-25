# Contributing to Undo

Thanks for helping. Bug reports, fixes, documentation and new features are all welcome.

**Quick links:** [Development guide](docs/DEVELOPMENT.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Documentation index](docs/README.md) · [Security policy](SECURITY.md) · [Changelog](CHANGELOG.md)

**On this page:**

* [Reporting a bug](#reporting-a-bug)
* [Suggesting a feature](#suggesting-a-feature)
* [Making a change](#making-a-change)
* [Checks before a pull request](#checks-before-a-pull-request)
* [Rules the code follows](#rules-the-code-follows)
* [Documentation and changelog](#documentation-and-changelog)
* [License](#license)

---

## Reporting a bug

**Security problems:** do **not** open a public issue. Follow the [security policy](SECURITY.md).

Otherwise, [open an issue](https://github.com/Madhur-Prakash/Undo/issues/new) with:

* **What you did, what you expected, and what happened.**
* **Version and system:** the output of `undo --version`, and your OS (for example Windows 11,
  Ubuntu 24.04).
* **How Undo runs:** installer, `uv tool install`, or from source; started at sign-in, systemd,
  or `undo start`.
* **Diagnostics:**

```sh
undo status
undo doctor
undo logs -n 100
```

* For a wrong comparison or restore, the version ids involved (from `undo versions FILE`).

Check [Troubleshooting](docs/TROUBLESHOOTING.md) first; many common problems are answered there.

**Before you paste logs, check them for anything private:**

* file and folder names you would rather not share,
* the API token. It is never written to the log, but never paste the `api_token` file itself.

## Suggesting a feature

[Open an issue](https://github.com/Madhur-Prakash/Undo/issues/new) that describes:

* the problem you want solved (not only the solution),
* how you would use it: app, `undo` command, or `undo tui`.

For larger changes, discuss the approach in the issue before writing code.

## Making a change

1. **Fork** the repository and create a branch from `main`:

```sh
git clone https://github.com/<you>/Undo.git && cd Undo
git switch -c fix-short-description
```

2. **Set up** the development environment. It uses a separate data directory, `.dev-home/`, so your
   own Undo history is never touched:

```sh
make init            # or: ./make.sh init   (Git Bash)   or: python scripts/dev.py init
```

3. **Make the change.** How to run each part (daemon, CLI, TUI, app) is in
   [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#running-each-part).
4. **Add or update tests** for new behaviour ([test layout](docs/DEVELOPMENT.md#checks-before-you-commit)).
5. **Run the checks** below.
6. **Try it on a real install** if it touches the daemon, the installer or autostart
   ([how](docs/DEVELOPMENT.md#trying-your-changes-on-a-real-install)).
7. **Open a pull request** against `main`, saying what changed, why, and how you tested it.
   Link the issue it closes (`Closes #123`).

Keep a pull request to one topic. Small pull requests are reviewed faster.

## Checks before a pull request

```sh
make format          # ruff format + autofix
make lint            # ruff check, flutter analyze
make typecheck       # mypy
make test            # unit + integration tests
cd gui/undo_desktop && flutter test      # if you changed the app
```

* All of them must pass.
* **Dart files:** check them with `flutter analyze` only. Do not run `dart format` over the
  whole app: it reformats every file and buries the real change in the diff.
* Changes to concurrency, garbage collection or capture should also pass `make test-stress`.

## Rules the code follows

These protect people's files and history. A pull request that breaks one will not be merged.

* **Never overwrite a user's file silently.** Replacing a file needs an explicit overwrite, and
  the current content is saved as a version first.
* **Never write unverified data.** Stored content is checked against its hash before it is
  published and again before it is restored.
* **Crash-safe writes.** Data goes to staging, is synced and verified, and is published
  atomically before the database transaction commits.
* **One source of truth.** All logic lives in `backend/src/undo_core`, behind `UndoService`. The
  CLI, the TUI and the app only call its operations (directly or through the local API).
* **Short write transactions.** Hashing and compression happen before the `BEGIN IMMEDIATE`
  transaction that records the result.
* **The API stays local.** It binds to loopback and every route except `/ping` needs the token.
* **Same feature everywhere.** A user-facing feature should work in the app, the CLI and the TUI,
  or the pull request should say why not.
* Python 3.12+, type-annotated, checked with mypy, formatted and linted with ruff.

Background: [Architecture](docs/ARCHITECTURE.md), [Storage](docs/STORAGE.md),
[Recovery › Restore guarantees](docs/RECOVERY.md#restore-guarantees).

## Documentation and changelog

* **Docs:** update the page that describes what you changed. The
  [documentation index](docs/README.md) lists every page. Keep the style: short bullet points,
  and commands in their own copyable code blocks.
* **Changelog:** add a line to [CHANGELOG.md](CHANGELOG.md), in the topmost section, under the
  matching heading. Describe the change from the user's point of view.
* **API changes:** run `make docs` to regenerate [docs/API_OPENAPI.json](docs/API_OPENAPI.json),
  and update [docs/API.md](docs/API.md).
* **New settings:** add them to the settings table in [docs/CLI.md](docs/CLI.md#settings) and to
  the app's Settings page.

## License

Undo is released under the [MIT license](LICENSE). By contributing, you agree that your
contributions are licensed under the same terms.

---

Related: [Development](docs/DEVELOPMENT.md) · [Security policy](SECURITY.md) · [Documentation index](docs/README.md)
