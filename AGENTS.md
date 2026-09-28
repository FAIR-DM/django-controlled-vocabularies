# AGENTS.md — Agent configuration for django-controlled-vocabularies

<!-- Thin index only — bloat here = ignored instructions. Details live in the pointed-to
     files: CONTEXT.md, docs/adr/, docs/agents/. -->

django-controlled-vocabularies is a Django app for **managing, publishing, and consuming SKOS
controlled vocabularies** in research infrastructure. Relational models are the source of truth,
and RDF is a projection produced only at the import/export boundary. See the
[`README`](README.md) for scope, [`docs/index.md`](docs/index.md) for the manual,
[`CONTEXT.md`](CONTEXT.md) for the ubiquitous language, and [`docs/adr/`](docs/adr/) for the
reasoning behind the design.

## Stack & commands

- **Stack:** Python 3.11+, Django 5.2+, uv-managed. Installable Django app (also runnable standalone).
- **Install:** `uv sync && uv run pre-commit install` — the second step wires the git hook so the full pre-commit suite runs on every commit locally. The CI **Code Quality** job runs the same `.pre-commit-config.yaml`, so skipping the local install lets hook-only failures (end-of-file-fixer, trailing-whitespace, check-yaml, uv-lock) reach CI instead of being caught at commit time.
- **Pre-commit (run the whole suite):** `uv run pre-commit run --all-files` — this is the authoritative pre-push gate; it is a superset of the individual commands below (it also runs the file-hygiene and uv-lock hooks). Prefer it over running the tools piecemeal.
- **Test:** `uv run pytest`
- **Lint:** `uv run ruff check .`
- **Format:** `uv run ruff format .`
- **Type-check:** `uv run mypy`
- **Deps audit:** `uv run deptry .`
- **Build:** `uv build`

## Agent skills

### Issue tracker

Issues and PRs tracked in GitHub Issues via the `gh` CLI. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

Canonical five-label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, `wontfix`). See [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context layout — `CONTEXT.md` at the root, `docs/adr/` for the reasoning behind the design.
See [`docs/agents/domain.md`](docs/agents/domain.md).

### CI checks

Required status checks (exact names), all reusable-workflow contexts from `django-mvp/shared`:

- `call-build / Code Quality`
- `call-build / Security Scan`
- `call-build / Build Package`
- `call-tests / Test Python 3.12, Django 5.2`
- `call-tests / Test Python 3.12, Django 6.0`
- `call-tests / Test Python 3.13, Django 5.2`
- `call-tests / Test Python 3.13, Django 6.0`
- `call-tests / Test Python 3.12, Django 6.1`
- `call-tests / Test Python 3.13, Django 6.1`

CI calls the reusable workflows in `django-mvp/shared`, pinned to a release tag of that repository.

## Development workflow

Feature work follows a spec-driven process: spec → plan → tasks → implement → review → PR, with
`specs/NNN-slug/` directories generated per feature (there is no Spec Kit install in the repo).
Project standards and the quality bar live in `CONSTITUTION.md`; the testing and code-documentation
rules it points to live in `docs/contributing/standards/`.
