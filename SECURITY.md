# Security

This repository contains application code and public chess reference data only.
Never commit runtime databases, session material, service credentials, purchase
tokens, `.env` or private backups. Do not post sensitive reports in public issues.
Report suspected vulnerabilities privately to the repository owner through the
existing private project channel, with reproduction steps and a redacted example.

See [the security review](docs/SECURITY_REVIEW.md) for scope, fixes, verification
and operational limits. Dependency findings are checked in GitHub Actions using
pip-audit and npm audit; static high-severity findings are gated with Bandit.
`requirements.lock` records the runtime versions reviewed for this release.

The default deployment is loopback-only. Public use requires the site's own HTTPS
origin, secure cookies, a correctly configured trusted reverse proxy and merchant
onboarding tests before enabling real payments. Do not expose the legacy service
or engine workers directly. Admin access grants full control of this application.
