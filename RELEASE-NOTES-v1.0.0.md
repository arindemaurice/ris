# RIS v1.0.0 - Initial public release

**Release type:** Initial public release / early access  
**Product:** Reliable Internet Solutions (RIS), multi-tenant ISP management SaaS

## Included

- Public RIS product website and responsive ISP/customer workspace interface.
- Separate RIS platform-owner console and tenant-scoped ISP workspaces.
- ISP registration, owner verification workflow, trial plans and tenant-level package/customer/voucher/invoice/payment/router/agent records.
- Customer portal and local demo payment workflow.
- Flutterwave and MTN MoMo integration foundations with authenticated server-side verification paths.
- Payment-settlement idempotency and unique subscription-per-payment protection.
- FreeRADIUS SQL subscriber provisioning foundation and retry of eligible pending/failed provisioning.
- RouterOS API-SSL connection testing, RADIUS configuration workflow and read-only router health/session snapshot.
- Background worker for expiry and SaaS billing tasks.
- Windows, macOS and Linux installers/start scripts; Docker Compose deployment foundation.
- Android/iOS installable PWA access through a deployed HTTPS server.
- Added the missing `.env.example` template required by first-run setup and Docker image builds, plus automated regression tests for bootstrap-secret generation and safe non-overwrite behavior.
- Updated installation, security, audit and release documentation.

## Verification

- Automated backend suite: **29 tests passed** in the release workspace.
- Python compilation, frontend JavaScript syntax and Unix shell syntax checks are part of the release validation.
- Docker image build, Windows PowerShell execution, production reverse-proxy deployment and live third-party interoperability have not been certified in this environment.

## Known limitations - read before using with paying customers

- Public guest captive-portal checkout is not a fully live payment-to-internet activation workflow.
- Direct MikroTik subscriber lifecycle (create, renew, suspend, disconnect, rollback) is incomplete.
- FreeRADIUS accounting ingestion, combined quota calculation, CoA/Disconnect delivery and acknowledgement/retry are incomplete.
- PPPoE lifecycle automation is incomplete.
- Agent commission settlement, refunds and full financial reconciliation are incomplete.
- MFA, full staff invitation/recovery workflows, database-level row-level security, independent penetration testing and production monitoring are not complete.
- Actual Flutterwave/MTN merchant onboarding, SMS/email sender setup, FreeRADIUS daemon and RouterOS hardware testing require operator-owned accounts and an isolated lab.

## Upgrade and deployment

This is the first public RIS release. Follow `INSTALLATION-GUIDE.md` for local setup and `PUBLISHING-CHECKLIST.md` for a public deployment. Never copy an existing private `.env` into a public ZIP or Git repository. Keep the generated bootstrap password and encryption keys private.
