# RIS implementation audit and production roadmap

**Baseline reviewed:** 6 November 2026; foundation hardening release 2.2.0  
**Product:** Commercial multi-tenant ISP SaaS platform  
**Baseline:** unified RIS public site, platform admin, ISP workspace and end-customer portal.

## Implemented in this release

- SQLite local mode and a PostgreSQL-compatible connection layer; Compose now starts PostgreSQL, RIS API and a separate maintenance worker.
- Generated per-installation application/session/password/OTP secrets, Fernet credential-encryption key, PostgreSQL password and initial platform-admin password.
- Tenant-scoped provider credentials encrypted at rest; status APIs do not return secret values.
- Flutterwave hosted checkout, `verif-hash` webhook authentication and server-side transaction verification against payment reference, amount and currency.
- MTN MoMo Collections token acquisition, RequestToPay submission, callback notification and independent status API verification against external reference, amount and currency.
- Pending checkout idempotency: a repeated request reuses the current open attempt instead of making another provider request; a partial unique index protects concurrent open attempts.
- RouterOS API-SSL connection testing with certificate/hostname verification enabled.
- Explicit MikroTik RADIUS configuration for hotspot/PPP services, accounting ports, hotspot profile RADIUS use, PPP AAA and incoming RADIUS messages.
- Encrypted per-router API and shared-secret credentials.
- FreeRADIUS SQL provisioning into `radcheck`/`radreply` when PostgreSQL and `RIS_RADIUS_SQL_ENABLED=true` are configured.
- RADIUS session timeout, RouterOS rate-limit attribute, port/device limit and conservative directional byte caps.
- Background worker for customer subscription expiry, cleanup of RADIUS check/reply entries, SaaS subscription invoice creation, grace windows and workspace suspension.
- Role-filtered UI navigation and read-only router screen for support roles.
- Updated setup scripts, Linux/Windows launchers, Docker image and deployment README.

## Automated verification

The release test suite currently exercises:

- ISP onboarding with separate OTPs and workspace creation.
- Customer onboarding, package purchase and development-mode activation.
- Password change, session handling and CSRF protection.
- Tenant isolation at the API/query layer.
- Provider secret encryption and non-disclosure.
- SaaS plan selection, plan entitlements and router/customer limits.
- Worker recurring invoice idempotency and past-due status.
- Flutterwave checkout/verification via mocked HTTP responses and duplicate checkout request protection.
- RouterOS API-SSL management flow via a mock RouterOS API client.
- FreeRADIUS SQL attribute creation and RouterOS speed/quota mapping via a fake database connection.

Run `python -m pytest -q`, `python -m py_compile backend/app.py backend/worker.py backend/setup.py` and `node --check frontend/assets/app.js`. The baseline suite contained 17 tests. Release 2.2.0 adds two security regression tests; the current suite contains 19 tests.

## What was not tested live

- No real Flutterwave merchant key or transaction was used.
- No real MTN MoMo merchant credentials or handset request was used.
- Gmail App Password and Africa's Talking key are not present in the archive; live email/SMS delivery has not been verified.
- PostgreSQL code path has not been run against a live PostgreSQL server in this environment. Docker Compose is provided but deployment must be tested by the operator.
- No FreeRADIUS daemon was installed or contacted; SQL writes are gated by `RIS_RADIUS_SQL_ENABLED` and require the correct full schema/version and database permissions.
- MikroTik operations have only been verified with a mocked RouterOS API client; no physical RB951/router was configured.
- Airtel Money credentials can be stored only in future extension; a Uganda live adapter is not implemented.

## Important remaining gaps

### 1. Database and tenant isolation

- Implement Alembic or another versioned migration system.
- Implement PostgreSQL Row-Level Security (or an externally reviewed equivalent) so tenant isolation is enforced by the database, not only API query filters.
- Add a data import tool to migrate existing SQLite prototype data to PostgreSQL while verifying every foreign key and tenant relationship.
- Use separate least-privilege roles for the RIS app, FreeRADIUS and backup/maintenance operations.
- Test concurrent writes, deadlock handling, connection pool limits, migrations, encrypted backups and restore/PITR.

### 2. Authentication and access lifecycle

- Add staff invitations, staff removal, a detailed permission matrix, MFA, forgot-password/recovery, email/phone re-verification, OTP resend cooldown and IP/device/phone abuse controls.
- Add account/device session view and revocation, audit search/export and security alerting.
- Add verified contact and duplicate-account dispute workflows.

### 3. Payments and finance

- Complete Flutterwave and MTN sandbox-to-live certification with real merchant accounts, actual payment/failed/cancelled/duplicate/late-webhook scenarios and reconciliation.
- Add platform-subscription payment idempotency and reconciliation tests equivalent to customer payment paths.
- Add refunds, reversals, chargebacks, partial payments, manual payment approval, bank/mobile-money reconciliation and accounting export.
- Implement Airtel Money Uganda only against the approved API contract and run end-to-end signed callback and verification tests.
- Add durable webhook event retry/monitoring and alert on unmatched payments.

### 4. Network automation

- Validate RouterOS API property names and behavior on supported RouterOS 7 releases and test a full lab Hotspot and PPPoE subscriber lifecycle.
- Add health polling, router config snapshots, safe rollback, rate-of-change alerts and multi-site monitoring.
- Deploy FreeRADIUS using the schema shipped with the exact installed release. Confirm `authorize`, `accounting`, NAS matching, PAP/CHAP/EAP needs and SQL module queries.
- Ingest `radacct` accounting sessions and calculate combined upload/download usage by customer, ISP, AP, router and time window.
- Add robust aggregate quota enforcement and RADIUS CoA/Disconnect sender/retry/acknowledgement for already-connected sessions.
- Implement voucher authentication/redemption, batch lifecycle, QR/print export, agent allocation and commission settlement.
- Test PPPoE profiles/service types, IP pool management, static IPs and suspension/renewal handling.

### 5. SaaS product operations

- Add self-service tenant plan checkout, plan change scheduling, proration, usage overages, dunning, notification schedules and fully tested subscription renewal.
- Complete feature gates on every relevant write path and API endpoint.
- Add tenant custom-domain verification, automated TLS, branded emails/portals and configurable payment integrations.
- Add support ticketing, tenant audit export, platform incident status, observability, usage metering and service-level monitoring.

### 6. Production engineering

- Add Redis and a durable task queue (or another durable scheduler) instead of relying on one loop worker; use distributed locks for job idempotency.
- Use secrets manager/KMS for production keys; rotate keys without data loss.
- Run OWASP ASVS-based security review, dependency scanning, SAST, DAST, load tests and independent penetration tests.
- Add central logs/metrics/traces, alerting, error budget and incident runbooks.
- Enforce TLS at the reverse proxy, secure trusted-proxy headers, strict host/CORS allowlists, rate limits and hardened HTTP security headers.

## Release assessment

RIS is a **more complete integration prototype**, not yet a production-ready commercial ISP platform. The local product flows are tested and provider/network adapters are present, but live operation remains dependent on third-party credentials, PostgreSQL and FreeRADIUS deployment, router testing and the remaining security/operations work listed above.


## Public website redesign (6 November 2026)

- Replaced the previous public homepage with a new RIS SaaS positioning and page flow: platform overview, capabilities, private ISP workspace configuration, onboarding, security and account calls to action.
- Removed public internet package/pricing catalogue content. ISP service packages remain configurable from the authenticated ISP workspace; the customer portal displays only the tenant provider’s configured offers.
- Refreshed sign-in and registration visual styling to align with the new RIS identity.
- Added a visible fallback message if the frontend application script fails to load instead of leaving the visitor on an endless loading screen.
- Public dashboard metrics are illustrative preview content and must not be represented as real customer or network statistics.


## Foundation hardening completed in 2.2.0

- Release archives exclude `.env`, SQLite database files, Python bytecode and pytest/runtime caches. First-run setup creates fresh local secrets and a fresh bootstrap administrator password.
- Added `itsdangerous` to runtime requirements for Starlette session middleware.
- Registration password minimum raised to 12 characters in both API validation and browser forms.
- Staff-only package and voucher listing endpoints no longer accept customer-role sessions.
- Customer creation validates that an assigned package belongs to the same ISP and validates service type/status values.
- Tenant ownership is included in relevant customer/package joins used by customer, invoice, payment, voucher and subscription views.
- Added regression tests for customer authorization and cross-tenant package assignment.

## Still not complete

This hardening release is not the final RIS product. Captive Portal Designer and public hotspot login/payment flow, voucher redemption, staff invitation/agent self-service, production-grade PostgreSQL Row-Level Security, formal versioned migrations, authentication rate limiting/MFA/recovery, live payment-provider certification, live router/FreeRADIUS testing, monitoring, backup/restore drills and independent security review remain development work. Do not expose the development build as a production service.


## v2.3.0 implementation update

Implemented a tenant-scoped captive portal configuration API and owner-facing designer, public portal package catalogue, local simulated checkout, one-time voucher redemption, and trial session records. Public trial flows deliberately do not create RADIUS users or change router state. Remaining production work includes payment-provider checkout from the public unauthenticated portal, verified webhooks/idempotency, router hotspot provisioning, RADIUS/CoA/accounting, abuse/rate limiting, custom domain/TLS automation, portal asset uploads, and complete responsive/browser/device testing.


## v2.4.0 operations update (6 November 2026)

### Implemented in this update

- Platform owner login supports the configured administrator display name as well as the bootstrap email. `/super-admin` opens a dedicated restricted sign-in screen. The public footer links only the text **RIS Tech** to that route.
- Platform owner customer console lists customer records across tenants, filters by ISP workspace, searches customer and ISP fields, creates customer records in a selected tenant, and suspends/reactivates/archives records. Platform actions are audited against the affected tenant.
- ISP customer directory supports search, contact editing, suspension/reactivation, and soft archival. Archived customer records remain available for financial history and audit.
- Network account state is updated when a customer is suspended or archived. With the FreeRADIUS SQL integration enabled, the subscriber's `radcheck` and `radreply` authorization rows are removed to block new authentication; reactivation rebuilds the RADIUS rows from the encrypted network credentials and current package.
- Regression suite expanded from 23 to 26 tests.

### Comparison with established ISP billing workflows

The feature comparison used PHPNuxBill's public documentation and repository overview. Its documented core flow includes plan selection/payment, creation of subscriber access in MikroTik or FreeRADIUS, scheduled expiry cleanup, Hotspot and PPPoE, multiple routers, vouchers, payment gateways and staff roles. RIS has corresponding foundations for several of these modules, but its live lifecycle is incomplete. The comparison is a feature/architecture benchmark only; no PHPNuxBill source code was copied.

### Still not operationally complete

1. Public captive-portal guest checkout is still a demo-only workflow in development; production guest portal does not yet collect payment and activate access automatically.
2. Payment verification can create a subscription and RADIUS SQL records, but there is no complete end-to-end test against a real payment provider, FreeRADIUS daemon and MikroTik router.
3. Direct MikroTik hotspot/PPPoE subscriber provisioning, per-package router assignment, live session listing/disconnect, router health polling and rollback are incomplete.
4. FreeRADIUS accounting ingestion (`radacct`), combined quota calculation, CoA/Disconnect delivery and acknowledgement/retry are incomplete. A suspended user may retain an already-authenticated session until the session expires or the router disconnects it.
5. Agent commission calculation/settlement, finance reconciliation/refunds, tenant staff invitations, MFA/recovery, global support tickets and production monitoring are not complete.
6. The live RB951 must not be used for destructive tests. Validate on a lab router or isolated test configuration first.

### Verification performed for v2.4.0

- `python -m py_compile backend/app.py backend/setup.py`
- `node --check frontend/assets/app.js`
- `python -m pytest -q` — 26 tests passed in the local automated test environment.

These checks verify local application behavior only. They do not establish production readiness or successful operation against external network/payment services.


## v2.6.0 update (7 November 2026)

- Customer payment settlement now has a conditional status transition and a unique subscription-per-payment database constraint. Repeated verification returns the already-created subscription rather than losing its reference or creating another subscription.
- Maintenance worker retries eligible active FreeRADIUS accounts whose provisioning state is pending/failed after temporary SQL integration errors.
- ISP users can request a tenant-scoped, read-only RouterOS health/session snapshot: router identity, RouterOS version, uptime, CPU/memory snapshot, active Hotspot sessions and active PPP sessions. This is live read-only visibility, not yet router subscriber provisioning or disconnect.
- Regression suite: 27 tests pass in the current local environment. Real PostgreSQL, FreeRADIUS and physical RouterOS interoperability remain unverified.


## v1.0.0 first public release packaging (7 November 2026)

- Published version metadata as `1.0.0` in the FastAPI application, workspace UI, service-worker cache and `VERSION` file.
- Added the previously missing `backend/.env.example` file. `backend/setup.py` requires this template to create the private `.env`; the Dockerfile also copies it. Added automated tests proving first-run secrets are generated and existing `.env` files are not overwritten.
- Added first-publication, public hosting and OS installation documentation.
- Bound the Docker-published API port to host loopback (`127.0.0.1:8000`) so a reverse proxy can expose HTTPS without publishing the application port directly.
- Verification in the final release workspace: 29 automated tests passed; Python compilation, JavaScript syntax and Unix shell syntax checks passed. Windows PowerShell execution, Docker image build and real payment/FreeRADIUS/RouterOS integration were not available for certification.

The release remains early access. The functional limitations listed above are still applicable; the v1.0.0 label is the first public product version, not a claim of production certification.
