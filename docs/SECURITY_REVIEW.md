# Security and technical delivery review — 2026-11-23

## Scope and evidence

Reviewed Studio authentication, CSRF/origin checks, tenant ownership, administrative
authorization, feature gates, SQLite access and deletion, AI credential handling,
payment settlement and callbacks, Google Play verification, media handling,
public-data export, browser rendering, dependencies and the deployed service's
listening ports. Also inspected the legacy API's separate API-key boundary.

This is a source review, regression suite and controlled deployment verification;
it is not an independent penetration-test certificate or proof that every possible
vulnerability or functional defect has been eliminated.

## Findings corrected

| Finding | Correction and regression coverage |
|---|---|
| Sensitive values could be echoed by validation errors outside the control APIs | All Studio validation responses omit submitted inputs and validator context; tested with an invalid password |
| Concurrent requests could bypass the attempt counter | SQLite `BEGIN IMMEDIATE` serializes counter checks/increments; expired counters are pruned; 12 concurrent attempts admit exactly the configured 3 |
| Changing the email address being attacked bypassed the per-account login counter | Added an IP-wide login budget in addition to the existing account/IP budget |
| Unknown accounts skipped expensive password verification | A random dummy PBKDF2 hash equalizes the password-verification path without creating an account |
| Request bodies were not bounded before JSON validation | Streaming and declared-length limits apply before dispatch; oversized requests, including chunked bodies, return 413 |
| Older course APIs bypassed the curriculum plan flag | The same server-side feature gate now covers `/api/course` and its children |
| Deleting a user with new control-plane rows could violate foreign keys | Atomic removal of nonfinancial control rows before deletion; billing-bound accounts receive an explicit 409 for administrative resolution instead of partial deletion or 500 |
| A sole administrator could attempt self-deletion | Administrative self-deletion is rejected; transfer/demotion must happen first |
| Callback capabilities and redirect JWT query values could enter access logs | Uvicorn access logging strips query values and callback capabilities |
| Request Host was unconstrained | TrustedHost middleware permits the configured site hostname plus loopback/test origins; untrusted Host receives 400 |
| Discount-only settlement could undo an administrative access hold | Recheck the hold while committing a zero-amount grant |
| Security validation used optimization-removable `assert` statements | Google service-account type/RSA strength and RTDN package checks now raise explicit errors |
| cryptography version bounds allowed versions predating published fixes | Require cryptography 50.0.2+, update framework floors and record audited resolved dependencies in `requirements.lock` |

Security headers retain CSP without unsafe inline scripts/styles, no-store for
account responses, nosniff and frame denial. Added camera/microphone/geolocation
restrictions and HSTS when a configured HTTPS origin uses secure cookies.

## Verification

- New focused regression module: `tests/test_security_review.py` (9 tests).
- Existing control/payment/Google, teacher, tenant, knowledge, learning, engine
  and interface regression suites remain in GitHub Actions.
- Python requirement resolution: 22 runtime packages, no known vulnerabilities
  reported by pip-audit at the review timestamp. This is advisory-database coverage,
  not a guarantee about unknown vulnerabilities.
- npm audit: zero reported vulnerabilities in the current lockfile.
- Bandit reviewed 27 medium B608 reports: identifiers/clauses originate from fixed
  code allowlists or placeholder generation; request values use SQLite parameters.
  No high-severity finding was reported. Low B105 reports include credential-field
  names/test strings, not embedded production credentials; optional invalid QR
  data is intentionally ignored. Security-related B101 asserts were removed.
- Public database checks cover SHA-256, fresh allowlisted construction, absence
  of private/cache rows, foreign keys and all 5,048 puzzle move sequences.
- Before deployment, runtime source hashes are compared to the reviewed baseline;
  consistent private SQLite backups and the previous image/Compose file provide
  rollback. Only the Studio web service is recreated; existing analysis workers
  and the legacy service are preserved. Scheduled jobs use the corrected image.

Reproduce locally:

```bash
pip install -r requirements.lock
PYTHONPATH=.:tests python -m unittest test_security_review test_control_center test_google_play test_database_export -q
pip-audit -r requirements.lock
bandit -r studio main.py -lll
npm ci
npm test
npm audit --audit-level=moderate
```

## Handoff limits and operational requirements

- The inspected Chess Studio and legacy listeners bind to `127.0.0.1:8001` and
  `127.0.0.1:8000`. The machine also hosts ports 22/80/443 and other loopback
  services; those unrelated applications and the entire operating system have
  not been independently audited or upgraded in this task.
- Keep the current SSH-tunnel deployment private until a domain/reverse proxy is
  configured. For public hosting set `STUDIO_BASE_URL=https://YOUR-DOMAIN` and
  `STUDIO_COOKIE_SECURE=true`. Trust forwarded client addresses only from the
  actual reverse proxy; never trust arbitrary internet-supplied X-Forwarded-For.
- Payment gateways remain disabled until the owner supplies merchant credentials
  and completes real sandbox contracts/onboarding. Mocked tests cannot certify
  the merchant's live API contract. Google Play still requires an Android app,
  Play Console products and authenticated RTDN setup.
- Private credentials have filesystem permissions, not independent at-rest
  encryption. Protect host/root access and backup access accordingly. Password
  reset email, email/Chess.com ownership verification and administrative MFA are
  not implemented; do not describe them as available.
- No destructive production fuzzing, real financial transactions, credential
  rotation, operating-system reboot or change to unrelated services was performed.
- Updates and backups remain necessary. Re-run dependency checks on every release;
  the lockfile does not replace security maintenance or restore drills.

Primary references: [cryptography release notes](https://github.com/pyca/cryptography/blob/main/CHANGELOG.rst/),
[Starlette advisories](https://github.com/Kludex/starlette/security/advisories),
[ZainCash](https://docs.zaincash.iq/), [FIB](https://fib.iq/integrations/web-payments/),
[Google Play security](https://developer.android.com/google/play/billing/security).
