# Security Policy

## Reporting a Vulnerability

We take the security of llm-apipool seriously. If you discover a security vulnerability, please follow these steps:

1. **Do not** disclose the vulnerability publicly (e.g., in GitHub Issues, Discussions, or pull requests).
2. Send a detailed report to the maintainers via the **GitHub Security Advisory** tab:
   - Go to https://github.com/GFardad/llm-apipool/security/advisories/new
   - Provide a clear description of the vulnerability
   - Include steps to reproduce if possible
   - Note the affected version(s)

Alternatively, reach out directly via the repository's security contact if listed.

## What to Expect

- **Acknowledgment**: Within 48 hours of reporting
- **Initial triage**: Within 5 business days
- **Resolution timeline**: Depends on severity — critical issues are prioritized

We will coordinate with you on disclosure timing.

## Scope

This security policy covers the `llm-apipool` Python package, its CLI, TUI, proxy server, and frontend dashboard.

### In scope:
- Remote code execution
- Authentication/authorization bypass
- Exposure of API keys or secrets
- SQL injection or path traversal
- Cross-site scripting (XSS) in the dashboard

### Out of scope:
- Rate limiting issues (these are by design)
- Unvalidated provider responses (providers are trusted)
- Missing CSRF on internal endpoints (single-user by design)

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Responsible Disclosure

We request a 90-day disclosure window from the time of notification to allow time for a fix and release. We will credit reporters in the release notes (unless anonymity is requested).
