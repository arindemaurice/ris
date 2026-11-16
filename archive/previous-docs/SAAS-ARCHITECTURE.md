# RIS SaaS foundation

RIS is designed as a **multi-tenant, white-label ISP operations SaaS** sold to
independent internet providers. It is not a single-ISP installation.

## Foundation included
- PostgreSQL schema for tenant organizations, branding/custom domains, platform plans,
  tenant subscriptions, platform staff, ISP staff, and self-registering ISP customers.
- Tenant-scope helper requiring tenant context from verified authentication.
- PostgreSQL Row-Level Security (RLS) policy example for customer isolation.
- Platform/ISP role separation and SaaS subscription status model.

## Required architecture before production
1. Migrate the current SQLite payment ledger to PostgreSQL and add `tenant_id` to every
   ISP-owned table: payments, invoices, packages, vouchers, routers, RADIUS records,
   usage, agents, tickets, logs, and notification jobs.
2. Implement authentication with secure password hashing, short-lived access tokens,
   refresh-token rotation, MFA for platform admins, and server-side role checks.
3. Tenant selection must come from verified user membership/token claims. NEVER trust
   `tenant_id` sent in a form, query string, or arbitrary HTTP header.
4. Use PostgreSQL RLS and tenant-scoped repository/service methods. Test cross-tenant
   access attempts for every endpoint.
5. Platform owner manages tenant lifecycle, plans, billing, support access, and
   platform-wide analytics. ISP owner/admin sees only their own tenant.
6. Tenant branding and custom domain must be resolved server-side and safely mapped
   to a tenant; do not allow arbitrary domain-to-tenant claims.
7. Customer self-registration is tenant-specific: email/phone uniqueness is scoped
   within a tenant, with OTP verification, rate limiting, consent, and recovery.
8. ISP SaaS billing is separate from each ISP's end-customer internet billing.
9. Payment webhooks must verify provider signatures, amount, currency, tenant,
   reference, idempotency, and final provider status before activation.
10. Add backups, migrations, monitoring, audit logs, data retention/export/deletion,
    and documented incident recovery.

## Local development
- Existing frontend and Flask app remain included.
- `saas_schema.sql` is PostgreSQL-oriented and is NOT automatically applied to the
  existing SQLite app.
- `tenancy.py` is a helper template, not complete auth or production isolation.
- Do not deploy as production until the migration and security checklist above passes.
