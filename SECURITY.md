# Security Policy

IRO_agent is a **strictly read-only** diagnostic agent for industrial software systems. Security is a core design property, not an afterthought.

## Security model

- **Strict Read-Only boundary** — against the system being diagnosed, IRO_agent performs no file writes, no Git commits, and no business-database writes, and it exposes no arbitrary shell execution. The configuration wizard writes only IRO's own configuration.
- **Evidence provenance** — every diagnostic claim must be anchored to a concrete observation (a log line, a configuration key, or a database record).
- **Redacted auditing** — a dual-layer read-only interception plus redacted audit trails keeps credentials and other secrets out of logs and reports.

## Supported versions

| Version | Supported |
| :--- | :--- |
| 0.1.x | :white_check_mark: |

## Reporting a vulnerability

If you find a way to bypass the read-only boundary, inject a write, leak credentials, or otherwise undermine these safety guarantees, please report it **privately** rather than opening a public issue.

- **Preferred:** open a *private* draft security advisory via GitHub **Security → Advisories → New draft security advisory**.
- **Alternative:** email the project security contact at `security@your-org.example` (replace this placeholder with the maintainer's real address).

We aim to acknowledge reports within 5 business days and to publish a fix with an advisory. Please do not include production data or live credentials in a report.