# GitHub Copilot Instructions — ha-dtek

This file provides persistent context for GitHub Copilot so it understands the project
without needing to re-learn the codebase on every session.

---

## Project Overview

**ha-dtek** is a Home Assistant custom integration for **DTEK** electricity distribution
system operators (ДТЕК Дніпровські електромережі, Київські електромережі, Київські регіональні
електромережі, Одеські електромережі). It fetches both scheduled stabilization outages
(Графіки погодинних відключень / GPV) and local grid maintenance / emergency repair notices
directly from DTEK's regional portals.

- **Repo**: https://github.com/aavdberg/ha-dtek
- **Domain**: `dtek`
- **HA minimum version**: 2026.9.0
- **Python target**: 3.12+
- **Linter**: ruff (configured in `pyproject.toml`)

---

## Repository Structure

```
custom_components/dtek/
├── __init__.py                # Entry setup/unload, entry.runtime_data
├── manifest.json               # Integration metadata, version
├── const.py                    # Domain, URLs, defaults, attribute constants
├── models.py                   # DtekRuntimeData and entry models
├── config_flow.py              # Address lookup / manual queue selection flow
├── coordinator.py              # DtekDataUpdateCoordinator with backoff & error handling
├── binary_sensor.py            # binary_sensor.dtek_power_expected
├── sensor.py                   # Next outage, restore time, reason, group sensors
├── calendar.py                 # calendar.dtek_outages with scheduled events
├── diagnostics.py              # Sensitive data redaction for diagnostics
├── strings.json                # Source-of-truth translation strings (English)
├── translations/
│   ├── en.json
│   ├── nl.json
│   └── uk.json
└── api/
    ├── __init__.py             # API facade
    ├── client.py               # DtekApiClient (session, cookies, CSRF, retries)
    ├── endpoints.py            # DTEK DSO endpoints and AJAX method names
    ├── exceptions.py           # Typed DTEK exceptions
    └── models.py               # Typed address, outage, and schedule models

tests/
├── conftest.py                 # Stubs homeassistant.* modules for lightweight unit testing
├── test_api_client.py          # DTEK HTTP client, CSRF extraction, error handling tests
├── test_coordinator.py         # Coordinator polling and update tests
├── test_entities.py            # Binary sensor, sensor, and calendar unit tests
├── test_models.py              # Model serialization and typing tests
└── test_diagnostics.py         # Redaction verification tests

.github/
├── workflows/
│   ├── lint.yml                # Ruff lint + format check, pytest, HACS validation
│   ├── hassfest.yml            # Home Assistant hassfest validation
│   ├── gitleaks.yml            # Secret scanning
│   ├── copilot-review.yml      # Copilot auto code review on PRs to main & dev
│   ├── pre-release.yml         # Auto pre-release tag on every push to dev (for HACS beta testing)
│   └── release.yml             # Auto GitHub Release on merge to main (based on manifest version)
├── copilot-instructions.md     # THIS FILE
├── pull_request_template.md
└── ISSUE_TEMPLATE/
    ├── bug_report.yml
    ├── config.yml
    ├── documentation.yml
    ├── feature_request.yml
    ├── idea.yml
    └── support_question.yml
```

---

## Authentication and API Model

- **Session & CSRF**: DTEK uses an initial GET to the portal (e.g. `https://www.dtek-dnem.com.ua/ua/shutdowns`)
  to establish session cookies and obtain a CSRF token (`X-CSRF-Token`).
- **AJAX Requests**: Stateful POST requests to `/ua/ajax` with `X-Requested-With: XMLHttpRequest`
  and the CSRF token.
- **Rate limiting / WAF**: Requests must use realistic user agent headers and handle temporary 429
  or 5xx responses with exponential backoff.
- **Privacy**: User addresses, house numbers, and session cookies are private. Diagnostics must redact
  exact house numbers and session cookies.

---

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Production — HACS users install from here; auto GitHub Release on merge |
| `dev` | Development & testing — all features merge here first |
| `feature/*` | Individual features — PR to `dev` |
| `fix/*` | Bug fixes — PR to `dev` |
| `chore/*` | Non-code changes (docs, CI, repo tooling) — PR directly to `main` if completely unrelated to integration code |

Both `main` and `dev` are protected: PRs required, ruff lint must pass.

### ⚠️ CRITICAL RULE — Mandatory workflow for every change:

1. **Plan** — Save proposed changes to `plan.md`.
2. **Confirm** — Present the plan to the user and ask for approval before writing any code.
3. **Issue** — Create a GitHub Issue describing the change with thorough detail.
4. **Branch** — Create a branch from `dev` (`git checkout -b fix/...` or `feature/...`).
5. **Implement** — Make code changes, run `ruff check`, `ruff format --check`, and `pytest`.
6. **Push & PR** — Push branch and open a PR targeting `dev`.
7. **CI** — Wait for all CI checks to pass.
8. **Review** — Wait for Copilot code review, evaluate each comment, reply, and resolve the thread.
9. **Merge** — Squash merge into `dev`.
10. **Verify dev pre-release** — Verify `pre-release.yml` published `v<version>-beta.<N>`.

---

## Releasing — promoting `dev` → `main`

Only perform a release to `main` when the user explicitly instructs to do so.
1. Bump `manifest.json` version on `dev`.
2. Open release PR: `gh pr create --base main --head dev --title "release: vX.Y.Z"`.
3. Wait for CI & Copilot review.
4. Merge with merge commit (`gh pr merge <N> --merge`).
5. Verify `release.yml` published `vX.Y.Z`.
6. Bump dev version to next minor/patch.

---

## Code Conventions

- **Language**: English for all code, comments, docstrings, commit messages, PRs, and GitHub issues.
- **Python**: 3.12+, type hints required, `from __future__ import annotations` in every module.
- **Imports**: `from collections.abc import Callable, Mapping` (not `typing.Callable`).
- **Linter**: ruff — run `ruff check custom_components/` and `ruff format --check custom_components/`.
- **Commit style**: Conventional Commits (`feat:`, `fix:`, `docs:`, `ci:`, `refactor:`).
- **Home Assistant 2026.09 Standards**: Use `entry.runtime_data` (no `hass.data[DOMAIN]`), typed coordinator, modern entity descriptions.
- **Sensitive data**: Never commit real addresses, IP addresses, or session tokens.
