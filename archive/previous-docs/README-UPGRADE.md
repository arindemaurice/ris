# RIS Billing System: Upgrade and implementation notes

## What was improved in this pass
- Payment ledger is now persisted in SQLite instead of disappearing when the Flask process restarts.
- Indexed transaction lookup by customer and payment status.
- Production mode disables the test-success endpoint.
- Backend can run in a container; requirements and environment template included.
- Flask debug mode is no longer forced on in production.
- CORS origins can be restricted with `RIS_ALLOWED_ORIGINS`.

## Existing UI modules
The project already has pages for customers, packages, vouchers, payments, reports, usage, routers, and settings. Most pages currently use browser `localStorage`; this is acceptable for a local UI demo but **not** for a real billing service. Browser storage is not shared across administrators, can be edited by users, and has no server-side authorization or audit trail.

## SopraEnt feature comparison (public website/docs reviewed)
RIS should incrementally implement:
1. Tenant/ISP workspaces and strict tenant data isolation.
2. Staff accounts, roles and permission checks (RBAC).
3. Package catalog: time, speed, data quota, device limit, sales visibility.
4. Voucher batches: secure random codes, bulk generation, CSV/PDF printing, QR, status, activation/expiry.
5. Customer records, device history, subscription renewals and suspension.
6. MikroTik RouterOS API integration: router registration, credential encryption, health polling, profile/user provisioning, active-session view and disconnect.
7. Payment provider abstraction, hosted checkout, signed webhook, provider-side verification, idempotency, reconciliation and receipts.
8. RADIUS/Accounting: session start/stop, interim usage, quota enforcement and CoA disconnect.
9. PPPoE subscriber lifecycle and recurring renewal.
10. Agent/reseller stock, commission, collections and settlement.
11. SMS/WhatsApp notifications for receipts, vouchers, expiries and outages.
12. Captive portal branding/themes, responsive client flow and self-service portal.
13. Reports: revenue, payments, package performance, active/expired access, usage and CSV exports.
14. Audit log, backups/restore, monitoring, rate limits, secrets management and automated tests.

## Run locally
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then set credentials
python app.py
```
API health: `http://127.0.0.1:5000/api/health`

## Important production warning
This is a **staged improvement, not a production-ready SaaS release**. The UI still relies on `localStorage`; authentication/session data is client-controlled; payment callbacks and actual MikroTik/RADIUS provisioning are not yet complete. Do not sell access or store real customer secrets until those layers are implemented and security-reviewed. A secure production version should migrate to PostgreSQL, server-side sessions, password hashing, tenant-scoped authorization, migrations, signed webhooks, idempotent activation, and integration tests.
