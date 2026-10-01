# Plan: DTEK Home Assistant Integration Architecture and Roadmap

## Goal

Create a robust, modern Home Assistant (2026.09) custom integration for DTEK electricity distribution grids (ДТЕК Дніпровські електромережі, Київські електромережі, etc.) that delivers reliable power status predictions, planned maintenance schedules, and stabilization outage calendar events.

## Background & Problem Statement

Users in Ukraine experience two distinct forms of electricity disruptions:
1. **Stabilization Outages (GPV / Графіки погодинних відключень)**: Group-based rotational power outages coordinated with national transmission operator Ukrenergo and supplier YASNO.
2. **Local Grid Maintenance & Emergency Repairs**: Equipment repairs, transformer servicing, and local line maintenance conducted directly by DTEK as the Distribution System Operator (DSO).

While YASNO integrations expose generic schedule queues, local DTEK maintenance announcements (often communicated via Telegram bots) do not appear in YASNO calendars. This integration directly queries DTEK endpoints to bridge that gap.

## Target Architecture

### Core Components

```
custom_components/dtek/
├── __init__.py                # Entry setup/unload, entry.runtime_data
├── manifest.json               # Integration metadata, version 0.1.0
├── const.py                    # Domain, constants, endpoints, default intervals
├── models.py                   # DtekRuntimeData, EntryData models
├── config_flow.py              # Address lookup / manual queue selection flow
├── coordinator.py              # DtekDataUpdateCoordinator with backoff & error handling
├── binary_sensor.py            # binary_sensor.dtek_power_expected
├── sensor.py                   # Next outage, restore time, reason, group sensors
├── calendar.py                 # calendar.dtek_outages with scheduled events
├── diagnostics.py              # Sensitive data redaction for diagnostics
├── strings.json                # English translation source
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
```

## Implementation Phases & Issues

### Phase 1: API Client Foundation & Session Management
- Issue 1: Implement DTEK HTTP client with CSRF extraction, cookie jar, and retry logic.
- Issue 2: Build address resolution and house number group mapping parser (`method=getHomeNum`).

### Phase 2: Schedule & Outage Discovery
- Issue 3: Reverse-engineer and implement additional AJAX methods (`getSchedule`, `getFact`, `getPlan`).
- Issue 4: Create typed models for stabilization schedules, maintenance windows, and emergency outages.

### Phase 3: Home Assistant Coordinator & Flow
- Issue 5: Build `DtekDataUpdateCoordinator` with intelligent polling and backoff.
- Issue 6: Implement modern UI Config Flow with address search and manual group fallback.
- Issue 7: Add Options Flow for custom polling intervals and notification thresholds.

### Phase 4: Entity Platforms
- Issue 8: Implement `binary_sensor.dtek_power_expected` for immediate power availability state.
- Issue 9: Implement sensors for next outage, expected restore time, reason, and queue group.
- Issue 10: Implement `calendar.dtek_outages` with full start/end event intervals for planned shutdowns.

### Phase 5: Multi-Region & Diagnostics
- Issue 11: Support all DTEK DSO regional portals (Dnipro, Kyiv City, Kyiv Region, Odesa).
- Issue 12: Implement `diagnostics.py` with automatic PII and sensitive address redaction.

### Phase 6: Reliability, Testing & CI
- Issue 13: Build full unit test suite covering client, coordinator, entities, and config flow.
- Issue 14: Configure GitHub Actions CI (Ruff, Pytest, Hassfest, HACS validation, Gitleaks, Copilot Review).
- Issue 15: Create community templates, documentation, and pre-release/release workflows.

## Validation & Success Criteria

1. Strict compliance with Home Assistant 2026.09 conventions (`entry.runtime_data`, typed coordinators, async lifecycle).
2. Clean separation of concerns between API client and Home Assistant entity layers.
3. 100% passing unit tests and Ruff linting (`ruff check` + `ruff format --check`).
4. Proper redaction of user addresses and session identifiers.
5. GitHub repository with protected branches (`main`, `dev`) and beta pre-release pipeline.
