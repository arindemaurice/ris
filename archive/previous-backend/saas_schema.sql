-- RIS multi-tenant SaaS foundation (PostgreSQL)
-- Every ISP-owned row MUST include tenant_id and be queried through tenant scope.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug VARCHAR(80) UNIQUE NOT NULL,
  legal_name VARCHAR(200) NOT NULL,
  display_name VARCHAR(120) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'trial'
    CHECK (status IN ('trial','active','past_due','suspended','cancelled')),
  timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Kampala',
  currency CHAR(3) NOT NULL DEFAULT 'UGX',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_branding (
  tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  logo_url TEXT,
  primary_color VARCHAR(7) DEFAULT '#0B2B52',
  accent_color VARCHAR(7) DEFAULT '#00B8E4',
  portal_title VARCHAR(120),
  custom_domain VARCHAR(253) UNIQUE,
  settings JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS platform_plans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code VARCHAR(40) UNIQUE NOT NULL,
  name VARCHAR(100) NOT NULL,
  price NUMERIC(14,2) NOT NULL CHECK(price >= 0),
  currency CHAR(3) NOT NULL DEFAULT 'UGX',
  billing_period VARCHAR(12) NOT NULL CHECK(billing_period IN ('monthly','annual')),
  limits JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS tenant_subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  plan_id UUID NOT NULL REFERENCES platform_plans(id),
  status VARCHAR(20) NOT NULL DEFAULT 'trial'
    CHECK(status IN ('trial','active','past_due','suspended','cancelled')),
  starts_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ends_at TIMESTAMPTZ,
  provider VARCHAR(40),
  provider_subscription_ref VARCHAR(160),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tenant_subscriptions_tenant ON tenant_subscriptions(tenant_id);

CREATE TABLE IF NOT EXISTS platform_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email CITEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  full_name VARCHAR(160) NOT NULL,
  role VARCHAR(24) NOT NULL CHECK(role IN ('platform_owner','platform_support')),
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS tenant_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email CITEXT NOT NULL,
  password_hash TEXT NOT NULL,
  full_name VARCHAR(160) NOT NULL,
  role VARCHAR(24) NOT NULL CHECK(role IN ('owner','admin','finance','network_admin','support','agent')),
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id,email)
);

-- Example tenant-scoped tables. Apply tenant_id to all ISP-owned entities.
CREATE TABLE IF NOT EXISTS isp_customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email CITEXT,
  phone VARCHAR(32) NOT NULL,
  full_name VARCHAR(160) NOT NULL,
  password_hash TEXT,
  email_verified_at TIMESTAMPTZ,
  phone_verified_at TIMESTAMPTZ,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id,email),
  UNIQUE(tenant_id,phone)
);
CREATE INDEX IF NOT EXISTS idx_isp_customers_tenant ON isp_customers(tenant_id);

-- PostgreSQL Row-Level Security guardrail. Set app.tenant_id per transaction
-- after verifying the user's authenticated tenant membership.
ALTER TABLE isp_customers ENABLE ROW LEVEL SECURITY;
CREATE POLICY customer_tenant_isolation ON isp_customers
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true),'')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true),'')::uuid);
