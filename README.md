# Home Assistant – DTEK Outages (ha-dtek)

[![GitHub Release](https://img.shields.io/github/v/release/aavdberg/ha-dtek?include_prereleases&style=flat-square)](https://github.com/aavdberg/ha-dtek/releases)
[![Validate with hassfest](https://github.com/aavdberg/ha-dtek/actions/workflows/hassfest.yml/badge.svg)](https://github.com/aavdberg/ha-dtek/actions/workflows/hassfest.yml)
[![CI](https://github.com/aavdberg/ha-dtek/actions/workflows/lint.yml/badge.svg)](https://github.com/aavdberg/ha-dtek/actions/workflows/lint.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

Custom Home Assistant integration for **DTEK** electricity distribution grids
(ДТЕК Дніпровські електромережі, Київські електромережі, Київські регіональні
електромережі, Одеські електромережі). It fetches both scheduled stabilization
outages (Графіки погодинних відключень / GPV) and **local grid maintenance &
emergency repair notices** directly from DTEK's regional distribution portals.

---

## Why DTEK alongside YASNO?

In Ukraine, electricity supply and network distribution are handled by separate entities:

| Provider | Role | What it provides | What it lacks |
|---|---|---|---|
| **YASNO** | Electricity Supplier | Rotational queue stabilization schedules (GPV) | Local grid maintenance, transformer servicing, emergency cable repairs |
| **DTEK** | Distribution System Operator (DSO) | Real-time network status, house-specific queue mapping, scheduled maintenance windows | Consumer billing & tariff contracts |

### The Problem
Users often receive official DTEK Telegram notifications for scheduled maintenance (e.g. *вул. Центральна 1: 24-09-2026 10:00 - 17:00 geplande werkzaamheden*), but these critical maintenance windows do not appear in YASNO calendars.

**ha-dtek** queries DTEK directly to bridge this gap, providing accurate power status predictions and calendar events in Home Assistant.

---

## Features

- **Binary Sensor (`binary_sensor.dtek_power_expected`)**: Immediate `on`/`off` binary state indicating whether electricity is expected at your premises.
- **Countdown Sensors**:
  - `sensor.dtek_next_outage`: Timestamp of the next expected outage.
  - `sensor.dtek_restore_time`: Timestamp when power is scheduled to be restored.
  - `sensor.dtek_outage_reason`: Detailed reason (e.g., *Scheduled maintenance*, *Stabilization schedule*, *Emergency repair*).
  - `sensor.dtek_group`: Associated queue group (e.g., `GPV1.2`).
- **Calendar Platform (`calendar.dtek_outages`)**: Full calendar view of all planned maintenance windows and schedule intervals.
- **Automatic Address Resolution**: Enter your settlement, street, and house number to automatically resolve your DTEK queue and local maintenance notices.
- **Manual Queue Fallback**: Enter your queue (e.g. `GPV1.2`) directly if address lookup is temporarily unreachable.
- **Multi-Region DSO Portals**:
  - Dnipro Grids (`dtek-dnem.com.ua`)
  - Kyiv City Grids (`dtek-kem.com.ua`)
  - Kyiv Regional Grids (`dtek-krem.com.ua`)
  - Odesa Grids (`dtek-oem.com.ua`)
- **Privacy & Diagnostics**: Automatic redaction of exact house numbers and session cookies in diagnostic exports.

---

## Installation

### 1. Via HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=aavdberg&repository=ha-dtek&category=integration)

1. Open **HACS** in your Home Assistant instance.
2. Click the three dots menu (top right) → **Custom repositories**.
3. Add `https://github.com/aavdberg/ha-dtek` with category **Integration**.
4. Search for **DTEK Outages** and click **Download**.
5. Restart Home Assistant.

### 2. Manual Installation

1. Download the latest release from the [Releases page](https://github.com/aavdberg/ha-dtek/releases).
2. Copy the `custom_components/dtek` directory to your Home Assistant `config/custom_components/` folder.
3. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings → Devices & services → Add integration**.
2. Search for **DTEK Outages**.
3. Select your regional DSO (e.g. *Dnipro Grids*).
4. Choose setup method:
   - **Automatic address lookup**: Enter your city/settlement (e.g. `м. Дніпро`), street (`вул. Центральна`), and house number (`1`).
   - **Manual queue selection**: Directly enter your queue identifier (e.g. `GPV1.2`).
5. Click **Submit**.

---

## Automation Examples

### 1. Telegram Notification 24 Hours Before Planned Maintenance

```yaml
alias: "DTEK: Maintenance alert 24h in advance"
trigger:
  - platform: calendar
    event: start
    offset: "-24:00:00"
    entity_id: calendar.dtek_outages
action:
  - service: telegram_bot.send_message
    data:
      title: "⚠️ DTEK Planned Maintenance in 24 hours"
      message: >
        DTEK maintenance is scheduled to start tomorrow at
        {{ state_attr('calendar.dtek_outages', 'start_time') }}.
        Estimated restoration: {{ state_attr('calendar.dtek_outages', 'end_time') }}.
        Description: {{ state_attr('calendar.dtek_outages', 'description') }}.
```

### 2. Prepare EcoFlow / Home Battery 1 Hour Before Outage

```yaml
alias: "DTEK: Pre-charge EcoFlow battery 1h before outage"
trigger:
  - platform: calendar
    event: start
    offset: "-01:00:00"
    entity_id: calendar.dtek_outages
condition:
  - condition: numeric_state
    entity_id: sensor.ecoflow_battery_level
    below: 90
action:
  - service: switch.turn_on
    target:
      entity_id: switch.ecoflow_ac_fast_charge
  - service: notify.notify
    data:
      title: "🔋 Charging EcoFlow"
      message: "DTEK outage starts in 1 hour. Fast charging battery storage."
```

### 3. Emergency Blackout Safeguard

```yaml
alias: "DTEK: Power outage active"
trigger:
  - platform: state
    entity_id: binary_sensor.dtek_power_expected
    to: "off"
action:
  - service: notify.notify
    data:
      title: "⚡ Power Outage Active"
      message: >
        Power is off according to DTEK schedule.
        Expected restoration: {{ states('sensor.dtek_restore_time') }}.
        Reason: {{ states('sensor.dtek_outage_reason') }}.
```

---

## Development & Contributing

### Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements_test.txt ruff
```

### Running Checks

```powershell
# Lint & format check
ruff check custom_components/
ruff format --check custom_components/

# Run unit tests
pytest -v
```

### Branching & Merge Gate

- `main` is production; `dev` is the integration branch.
- Every change follows: Plan → Confirm → Issue → Branch from `dev` → PR to `dev` → CI green → Copilot review resolved → Squash merge into `dev`.
- Releases to `main` happen only when explicitly requested.

---

## License

This project is licensed under the [MIT License](LICENSE).
