# Security Policy

## Supported Versions

Only the latest release on the `main` branch and the latest beta release on the `dev` branch receive security patches.

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in this integration:

1. **Do not open a public issue.**
2. Report vulnerabilities privately via [GitHub Security Advisories](https://github.com/aavdberg/ha-dtek/security/advisories/new) or contact the maintainer directly.
3. Include detailed steps to reproduce the issue, along with an assessment of the vulnerability's impact.
4. Maintainers will acknowledge receipt within 48 hours and work with you to test and deploy a fix before public disclosure.

## Privacy & Sensitive Data

This integration interacts with DTEK regional portals to fetch public shutdown schedules and maintenance notices.

- **No credentials or passwords** are stored or transmitted.
- **Address information**: Physical street addresses and house numbers are used exclusively to query DTEK endpoints and are stored only within your local Home Assistant instance (`config/.storage/core.config_entries`).
- Diagnostics and logs automatically redact exact house numbers, cookies, and IP addresses.
- Please do not submit real personal addresses or house numbers in public issues or pull requests.
