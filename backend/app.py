"""RIS multi-tenant ISP SaaS application.

FastAPI backend with local SQLite and optional PostgreSQL, server-side sessions,
tenant-scoped operations, dual-channel onboarding, payment adapters, RouterOS API-SSL,
optional FreeRADIUS SQL provisioning and a separate recurring maintenance worker.
Production operation remains conditional on provider credentials and tested infrastructure.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import smtplib
import sqlite3
import uuid
from urllib.parse import urlparse
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
load_dotenv(BASE_DIR / ".env")

APP_NAME = "RIS | Reliable Internet Solutions"
ENVIRONMENT = os.getenv("RIS_ENV", "development").lower()
DB_PATH = os.getenv("RIS_DB_PATH", str(BASE_DIR / "data" / "ris.db"))
OTP_TTL_MINUTES = max(3, min(int(os.getenv("RIS_OTP_TTL_MINUTES", "10")), 30))
OTP_MAX_ATTEMPTS = max(3, min(int(os.getenv("RIS_OTP_MAX_ATTEMPTS", "5")), 10))
DEV_SHOW_OTP = ENVIRONMENT != "production" and os.getenv("RIS_DEV_SHOW_OTP", "true").lower() == "true"
PAYMENT_MODE = os.getenv("RIS_PAYMENT_MODE", "demo" if ENVIRONMENT != "production" else "live").lower()
BOOTSTRAP_EMAIL = os.getenv("RIS_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com").strip().lower()
BOOTSTRAP_ADMIN_NAME = os.getenv("RIS_BOOTSTRAP_ADMIN_NAME", "Maurice Arinde").strip() or "RIS Platform Administrator"
BOOTSTRAP_PASSWORD = os.getenv("RIS_BOOTSTRAP_ADMIN_PASSWORD", "")
APP_SECRET = os.getenv("RIS_SECRET_KEY", "")
PASSWORD_PEPPER = os.getenv("RIS_PASSWORD_PEPPER", "")
OTP_PEPPER = os.getenv("RIS_OTP_PEPPER", "")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ris")

@asynccontextmanager
async def lifespan(application: FastAPI):
    if ENVIRONMENT == "production" and (not APP_SECRET or not PASSWORD_PEPPER or not OTP_PEPPER or not os.getenv("RIS_CREDENTIALS_KEY", "").strip()):
        raise RuntimeError("Production requires RIS_SECRET_KEY, RIS_PASSWORD_PEPPER, RIS_OTP_PEPPER and RIS_CREDENTIALS_KEY.")
    init_db()
    yield


app = FastAPI(title=APP_NAME, version="1.0.0", docs_url="/api/docs" if ENVIRONMENT != "production" else None, redoc_url=None, openapi_url="/api/openapi.json" if ENVIRONMENT != "production" else None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET or "UNSAFE-DEV-ONLY-CHANGE-ME",
    session_cookie="ris_session",
    max_age=60 * 60 * 12,
    same_site="lax",
    https_only=ENVIRONMENT == "production",
)
allowed_origins = [x.strip() for x in os.getenv("RIS_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-CSRF-Token"])


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS tenants (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
 email TEXT NOT NULL, phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'trial',
 plan TEXT NOT NULL DEFAULT 'Starter', brand_name TEXT, brand_primary TEXT DEFAULT '#0b78d0',
 custom_domain TEXT, currency TEXT NOT NULL DEFAULT 'UGX', timezone TEXT NOT NULL DEFAULT 'Africa/Kampala',
 trial_ends_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
 full_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
 password_hash TEXT NOT NULL, role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
 created_at TEXT NOT NULL, last_login_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_tenant_email ON users(COALESCE(tenant_id,''), lower(email));
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_tenant_phone ON users(tenant_id, phone) WHERE phone <> '';
CREATE TABLE IF NOT EXISTS auth_sessions (
 id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS otp_challenges (
 id TEXT PRIMARY KEY, purpose TEXT NOT NULL, tenant_id TEXT,
 email TEXT NOT NULL, phone TEXT NOT NULL, payload_json TEXT NOT NULL,
 email_hash TEXT NOT NULL, sms_hash TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 expires_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_otp_created ON otp_challenges(email, created_at);
CREATE TABLE IF NOT EXISTS otp_delivery_logs (
 id TEXT PRIMARY KEY, challenge_id TEXT NOT NULL, channel TEXT NOT NULL,
 destination TEXT NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL,
 detail TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_otp_delivery_challenge ON otp_delivery_logs(challenge_id, created_at);
CREATE TABLE IF NOT EXISTS customers (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 user_id TEXT REFERENCES users(id) ON DELETE SET NULL, name TEXT NOT NULL,
 email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', address TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'active', service_type TEXT NOT NULL DEFAULT 'hotspot',
 package_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_customers_tenant ON customers(tenant_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_email ON customers(tenant_id, lower(email)) WHERE email <> '';
CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_phone ON customers(tenant_id, phone) WHERE phone <> '';
CREATE TABLE IF NOT EXISTS packages (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 name TEXT NOT NULL, service_type TEXT NOT NULL DEFAULT 'hotspot',
 price_minor INTEGER NOT NULL CHECK(price_minor >= 0), currency TEXT NOT NULL DEFAULT 'UGX',
 validity_hours INTEGER NOT NULL DEFAULT 24, data_limit_mb INTEGER NOT NULL DEFAULT 0,
 speed_down_kbps INTEGER NOT NULL DEFAULT 0, speed_up_kbps INTEGER NOT NULL DEFAULT 0,
 device_limit INTEGER NOT NULL DEFAULT 1, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_packages_tenant ON packages(tenant_id, active);
CREATE TABLE IF NOT EXISTS vouchers (
 code TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 package_id TEXT NOT NULL REFERENCES packages(id), batch_id TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'unused', assigned_agent TEXT, expires_at TEXT,
 redeemed_by TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_vouchers_tenant ON vouchers(tenant_id, created_at DESC);
CREATE TABLE IF NOT EXISTS invoices (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 customer_id TEXT NOT NULL REFERENCES customers(id), package_id TEXT,
 amount_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'UGX',
 status TEXT NOT NULL DEFAULT 'unpaid', due_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 customer_id TEXT NOT NULL REFERENCES customers(id), invoice_id TEXT REFERENCES invoices(id),
 amount_minor INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'UGX',
 provider TEXT NOT NULL DEFAULT 'manual', reference TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, paid_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_payments_tenant ON payments(tenant_id, created_at DESC);
CREATE TABLE IF NOT EXISTS subscriptions (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 customer_id TEXT NOT NULL REFERENCES customers(id), package_id TEXT NOT NULL REFERENCES packages(id),
 status TEXT NOT NULL DEFAULT 'active', starts_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 data_limit_mb INTEGER NOT NULL DEFAULT 0, data_used_mb INTEGER NOT NULL DEFAULT 0,
 payment_id TEXT REFERENCES payments(id), created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_subscriptions_payment ON subscriptions(payment_id) WHERE payment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_subscriptions_customer_status ON subscriptions(tenant_id,customer_id,status,expires_at);
CREATE TABLE IF NOT EXISTS routers (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 name TEXT NOT NULL, host TEXT NOT NULL, api_port INTEGER NOT NULL DEFAULT 8729,
 site TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'unverified', last_seen TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 name TEXT NOT NULL, phone TEXT DEFAULT '', commission_rate REAL NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
 id TEXT PRIMARY KEY, tenant_id TEXT, actor_id TEXT, action TEXT NOT NULL,
 entity TEXT, entity_id TEXT, details_json TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tenant_integrations (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, secrets_encrypted TEXT NOT NULL, config_json TEXT NOT NULL DEFAULT '{}',
 enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(tenant_id, provider)
);
CREATE TABLE IF NOT EXISTS router_secrets (
 router_id TEXT PRIMARY KEY REFERENCES routers(id) ON DELETE CASCADE,
 tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 secrets_encrypted TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS network_accounts (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
 username TEXT NOT NULL, password_encrypted TEXT NOT NULL, service_type TEXT NOT NULL DEFAULT 'hotspot',
 status TEXT NOT NULL DEFAULT 'active', provision_status TEXT NOT NULL DEFAULT 'pending',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(tenant_id, username), UNIQUE(customer_id, service_type)
);
CREATE TABLE IF NOT EXISTS payment_attempts (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 payment_id TEXT NOT NULL REFERENCES payments(id) ON DELETE CASCADE, provider TEXT NOT NULL,
 provider_reference TEXT NOT NULL, provider_transaction_id TEXT, status TEXT NOT NULL DEFAULT 'pending',
 checkout_url TEXT, response_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(provider, provider_reference)
);
CREATE INDEX IF NOT EXISTS ix_payment_attempts_payment ON payment_attempts(payment_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_payment_attempts_open_payment ON payment_attempts(payment_id) WHERE status IN ('creating','pending');
CREATE TABLE IF NOT EXISTS webhook_events (
 id TEXT PRIMARY KEY, provider TEXT NOT NULL, tenant_id TEXT NOT NULL,
 event_reference TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'received', created_at TEXT NOT NULL,
 UNIQUE(provider, tenant_id, event_reference)
);
CREATE TABLE IF NOT EXISTS captive_portals (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
 enabled INTEGER NOT NULL DEFAULT 1, config_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_demo_orders (
 payment_id TEXT PRIMARY KEY REFERENCES payments(id) ON DELETE CASCADE,
 tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL, expires_at TEXT NOT NULL, redeemed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portal_sessions (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
 subscription_id TEXT REFERENCES subscriptions(id) ON DELETE SET NULL,
 source TEXT NOT NULL DEFAULT 'trial', status TEXT NOT NULL DEFAULT 'active',
 started_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_portal_sessions_tenant ON portal_sessions(tenant_id, started_at DESC);
CREATE TABLE IF NOT EXISTS saas_plans (
 code TEXT PRIMARY KEY, name TEXT NOT NULL, monthly_price INTEGER NOT NULL,
 annual_price INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'UGX',
 max_customers INTEGER NOT NULL, max_routers INTEGER NOT NULL, features_json TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tenant_subscriptions (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
 plan_code TEXT NOT NULL REFERENCES saas_plans(code), status TEXT NOT NULL DEFAULT 'trial',
 billing_cycle TEXT NOT NULL DEFAULT 'monthly', period_start TEXT NOT NULL,
 period_end TEXT NOT NULL, trial_ends_at TEXT, grace_ends_at TEXT, next_invoice_at TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS platform_invoices (
 id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
 subscription_id TEXT NOT NULL REFERENCES tenant_subscriptions(id), period_start TEXT NOT NULL,
 period_end TEXT NOT NULL, amount INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'UGX',
 plan_code TEXT REFERENCES saas_plans(code), billing_cycle TEXT NOT NULL DEFAULT 'monthly',
 status TEXT NOT NULL DEFAULT 'unpaid', due_at TEXT NOT NULL, paid_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(tenant_id, period_start)
);
CREATE INDEX IF NOT EXISTS ix_platform_invoices_tenant ON platform_invoices(tenant_id, created_at DESC);
CREATE TABLE IF NOT EXISTS platform_payments (
 id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES platform_invoices(id),
 provider TEXT NOT NULL, reference TEXT NOT NULL UNIQUE, amount INTEGER NOT NULL,
 currency TEXT NOT NULL DEFAULT 'UGX', status TEXT NOT NULL DEFAULT 'pending',
 checkout_url TEXT, created_at TEXT NOT NULL, paid_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_platform_payments_open_invoice ON platform_payments(invoice_id) WHERE status IN ('creating','pending');
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresCompat:
    """Small DB-API compatibility wrapper for the app's qmark SQL style."""
    def __init__(self, raw):
        self.raw = raw

    def execute(self, query, params=()):
        try:
            return self.raw.execute(query.replace("?", "%s"), params or ())
        except Exception as exc:
            if getattr(exc, "sqlstate", None) == "23505":
                raise sqlite3.IntegrityError(str(exc)) from exc
            raise

    def executescript(self, script):
        for statement in (part.strip() for part in script.split(";")):
            if statement and not statement.upper().startswith("PRAGMA "):
                self.execute(statement)

    def commit(self): self.raw.commit()
    def rollback(self): self.raw.rollback()
    def close(self): self.raw.close()


@contextmanager
def db_conn():
    if DATABASE_URL:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL is set but psycopg is not installed. Install backend/requirements.txt.") from exc
        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=8)
        conn = PostgresCompat(raw)
    else:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def seed_saas_plans(conn) -> None:
    plans = [
        ("starter", "Starter", 49000, 490000, 500, 3, {"hotspot": True, "pppoe": False, "agents": False, "api": False}),
        ("growth", "Growth", 119000, 1190000, 3000, 15, {"hotspot": True, "pppoe": True, "agents": True, "api": False}),
        ("scale", "Scale", 249000, 2490000, 15000, 75, {"hotspot": True, "pppoe": True, "agents": True, "api": True}),
        ("enterprise", "Enterprise", 0, 0, 1000000, 10000, {"hotspot": True, "pppoe": True, "agents": True, "api": True, "white_label": True}),
    ]
    for code, name, monthly, annual, customers, routers, features in plans:
        if not conn.execute("SELECT 1 FROM saas_plans WHERE code=?", (code,)).fetchone():
            conn.execute("INSERT INTO saas_plans(code,name,monthly_price,annual_price,currency,max_customers,max_routers,features_json,active) VALUES(?,?,?,?, 'UGX',?,?,?,1)",
                         (code, name, monthly, annual, customers, routers, json.dumps(features)))


def migrate_existing_schema(conn) -> None:
    """Small additive migrations for databases created by earlier RIS prototypes."""
    additions = {
        "network_accounts": {"provision_status": "TEXT NOT NULL DEFAULT 'pending'"},
        "platform_invoices": {"plan_code": "TEXT", "billing_cycle": "TEXT NOT NULL DEFAULT 'monthly'"},
        "platform_payments": {"checkout_url": "TEXT"},
    }
    for table, columns in additions.items():
        if DATABASE_URL:
            for column, definition in columns.items():
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        else:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for column, definition in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    # One successful payment may activate exactly one subscription. This
    # database-level guard protects against duplicate webhooks and concurrent
    # verification requests, including across multiple API workers.
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_subscriptions_payment ON subscriptions(payment_id) WHERE payment_id IS NOT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_subscriptions_customer_status ON subscriptions(tenant_id,customer_id,status,expires_at)")


def init_db() -> None:
    with db_conn() as conn:
        conn.executescript(SCHEMA)
        migrate_existing_schema(conn)
        seed_saas_plans(conn)
        # Every ISP receives a private default captive portal configuration.
        for tenant in conn.execute("SELECT id,name,brand_name,brand_primary FROM tenants").fetchall():
            if not conn.execute("SELECT 1 FROM captive_portals WHERE tenant_id=?", (tenant["id"],)).fetchone():
                config = {"headline": f"Welcome to {tenant['brand_name'] or tenant['name']}", "welcome_message": "Choose an internet package or enter your voucher to get connected.", "primary_color": tenant["brand_primary"] or "#087bd1", "background_color": "#071a2e", "footer_text": "Powered by RIS", "show_registration": True, "show_packages": True, "show_voucher": True}
                conn.execute("INSERT INTO captive_portals(id,tenant_id,enabled,config_json,created_at,updated_at) VALUES(?,?,1,?,?,?)", (new_id("CPT"), tenant["id"], json.dumps(config), now_iso(), now_iso()))
        # Backfill a SaaS subscription row for tenants created by older versions.
        for tenant in conn.execute("SELECT id,created_at,trial_ends_at FROM tenants").fetchall():
            if not conn.execute("SELECT 1 FROM tenant_subscriptions WHERE tenant_id=?", (tenant["id"],)).fetchone():
                start = tenant["created_at"]
                end = tenant["trial_ends_at"] or (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
                conn.execute("INSERT INTO tenant_subscriptions(id,tenant_id,plan_code,status,billing_cycle,period_start,period_end,trial_ends_at,next_invoice_at,created_at,updated_at) VALUES(?,?, 'starter','trial','monthly',?,?,?,?,?,?)",
                             (new_id("SAS"), tenant["id"], start, end, end, end, now_iso(), now_iso()))
        if BOOTSTRAP_PASSWORD and not conn.execute("SELECT 1 FROM users WHERE role='platform_admin' LIMIT 1").fetchone():
            user_id = new_id("USR")
            conn.execute(
                "INSERT INTO users(id,tenant_id,full_name,email,phone,password_hash,role,status,created_at) VALUES(?,NULL,?,?,?,?,?,'active',?)",
                (user_id, BOOTSTRAP_ADMIN_NAME, BOOTSTRAP_EMAIL, "", hash_password(BOOTSTRAP_PASSWORD), "platform_admin", now_iso()),
            )
        elif BOOTSTRAP_PASSWORD:
            # Migrate the previous generated bootstrap display name once, while
            # preserving any custom name an operator has already chosen.
            conn.execute("UPDATE users SET full_name=? WHERE role='platform_admin' AND lower(email)=? AND full_name='RIS Platform Administrator'", (BOOTSTRAP_ADMIN_NAME, BOOTSTRAP_EMAIL))


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", (password + PASSWORD_PEPPER).encode(), salt.encode(), 310_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, expected = stored.split("$", 2)
        actual = hashlib.pbkdf2_hmac("sha256", (password + PASSWORD_PEPPER).encode(), salt.encode(), 310_000).hex()
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_phone(value: Any) -> str:
    value = re.sub(r"[^0-9+]", "", str(value or "").strip())
    if value.startswith("0") and len(value) == 10:
        value = "+256" + value[1:]
    elif value.startswith("256"):
        value = "+" + value
    return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48].strip("-")


def otp_digest(code: str, challenge_id: str, channel: str) -> str:
    return hashlib.sha256(f"{OTP_PEPPER}:{challenge_id}:{channel}:{code}".encode()).hexdigest()


def safe_user(row: sqlite3.Row | dict) -> dict:
    data = dict(row)
    return {k: data[k] for k in ("id", "tenant_id", "full_name", "email", "phone", "role", "status") if k in data}


def audit(conn: sqlite3.Connection, user: dict | None, action: str, entity: str = "", entity_id: str = "", details: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_logs(id,tenant_id,actor_id,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (new_id("LOG"), (user or {}).get("tenant_id"), (user or {}).get("id"), action, entity, entity_id, json.dumps(details or {}, default=str), now_iso()),
    )


def credential_cipher():
    """Encrypt provider/router secrets at rest using a dedicated Fernet key."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError("Install cryptography to use encrypted integration credentials.") from exc
    key = os.getenv("RIS_CREDENTIALS_KEY", "").strip()
    if not key:
        if ENVIRONMENT == "production":
            raise RuntimeError("RIS_CREDENTIALS_KEY must be configured in production.")
        # Development-only deterministic fallback. setup.py creates a persistent key.
        key = __import__("base64").urlsafe_b64encode(hashlib.sha256((APP_SECRET or "RIS-DEV-ONLY") .encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_json(value: dict) -> str:
    return credential_cipher().encrypt(json.dumps(value).encode()).decode()


def decrypt_json(value: str) -> dict:
    return json.loads(credential_cipher().decrypt(value.encode()).decode())


def get_tenant_integration(conn, tenant_id: str, provider: str) -> tuple[dict, dict] | None:
    row = conn.execute("SELECT * FROM tenant_integrations WHERE tenant_id=? AND provider=? AND enabled=1", (tenant_id, provider)).fetchone()
    if not row:
        return None
    return decrypt_json(row["secrets_encrypted"]), json.loads(row["config_json"] or "{}")


def provider_status(conn, tenant_id: str) -> dict:
    result = {}
    for provider in ("flutterwave", "mtn_momo", "airtel_money"):
        row = conn.execute("SELECT enabled,config_json,updated_at FROM tenant_integrations WHERE tenant_id=? AND provider=?", (tenant_id, provider)).fetchone()
        result[provider] = {"configured": bool(row and row["enabled"]), "updated_at": row["updated_at"] if row else None}
    return result


def save_tenant_integration(conn, tenant_id: str, provider: str, secrets_in: dict, config: dict) -> None:
    allowed = {"flutterwave": {"secret_key", "webhook_secret"}, "mtn_momo": {"api_user", "api_key", "subscription_key"}, "airtel_money": {"client_id", "client_secret"}}
    if provider not in allowed:
        raise HTTPException(400, "Unsupported payment provider.")
    existing = get_tenant_integration(conn, tenant_id, provider)
    merged = dict(existing[0]) if existing else {}
    for key in allowed[provider]:
        value = str(secrets_in.get(key, "")).strip()
        if value:
            merged[key] = value
    required = allowed[provider]
    if not all(merged.get(k) for k in required):
        raise HTTPException(400, "All required credentials must be supplied at least once.")
    public_config = {}
    if provider == "flutterwave":
        env = str(config.get("environment", "test")).lower()
        if env not in ("test", "live"):
            raise HTTPException(400, "Flutterwave environment must be test or live.")
        public_config = {"environment": env}
    elif provider == "mtn_momo":
        env = str(config.get("environment", "sandbox")).lower()
        target = str(config.get("target_environment", "mtnuganda")).lower()
        if env not in ("sandbox", "production"):
            raise HTTPException(400, "MTN environment must be sandbox or production.")
        public_config = {"environment": env, "target_environment": target}
    else:
        env = str(config.get("environment", "sandbox")).lower()
        if env not in ("sandbox", "production"):
            raise HTTPException(400, "Airtel environment must be sandbox or production.")
        public_config = {"environment": env, "country_code": str(config.get("country_code", "UG")).upper(), "currency": str(config.get("currency", "UGX")).upper()}
    existing_row = conn.execute("SELECT id FROM tenant_integrations WHERE tenant_id=? AND provider=?", (tenant_id, provider)).fetchone()
    if existing_row:
        conn.execute("UPDATE tenant_integrations SET secrets_encrypted=?,config_json=?,enabled=1,updated_at=? WHERE tenant_id=? AND provider=?",
                     (encrypt_json(merged), json.dumps(public_config), now_iso(), tenant_id, provider))
    else:
        conn.execute("INSERT INTO tenant_integrations(id,tenant_id,provider,secrets_encrypted,config_json,enabled,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)",
                     (new_id("INT"), tenant_id, provider, encrypt_json(merged), json.dumps(public_config), now_iso(), now_iso()))


def settle_customer_payment(conn, payment, provider: str, transaction_id: str = "") -> dict:
    """Settle a verified customer payment exactly once.

    The conditional UPDATE is the concurrency gate: only the request that changes
    a non-paid payment to paid may create the subscription. A unique database
    index on subscriptions.payment_id is the second line of defence.
    """
    current = conn.execute(
        "SELECT * FROM payments WHERE id=? AND tenant_id=?",
        (payment["id"], payment["tenant_id"]),
    ).fetchone()
    if not current:
        raise HTTPException(404, "Payment not found.")

    if current["status"] == "paid":
        existing = conn.execute(
            "SELECT id FROM subscriptions WHERE payment_id=? AND tenant_id=?",
            (current["id"], current["tenant_id"]),
        ).fetchone()
        return {"status": "paid", "subscription_id": existing["id"] if existing else None, "already_paid": True}

    stamp = now_iso()
    changed = conn.execute(
        "UPDATE payments SET status='paid',paid_at=?,provider=? "
        "WHERE id=? AND tenant_id=? AND status<>'paid'",
        (stamp, provider, current["id"], current["tenant_id"]),
    )
    if changed.rowcount != 1:
        existing = conn.execute(
            "SELECT id FROM subscriptions WHERE payment_id=? AND tenant_id=?",
            (current["id"], current["tenant_id"]),
        ).fetchone()
        return {"status": "paid", "subscription_id": existing["id"] if existing else None, "already_paid": True}

    invoice = None
    if current["invoice_id"]:
        conn.execute(
            "UPDATE invoices SET status='paid' WHERE id=? AND tenant_id=?",
            (current["invoice_id"], current["tenant_id"]),
        )
        invoice = conn.execute(
            "SELECT package_id FROM invoices WHERE id=? AND tenant_id=?",
            (current["invoice_id"], current["tenant_id"]),
        ).fetchone()

    subscription_id = None
    if invoice and invoice["package_id"]:
        subscription_id = activate_subscription(
            conn, current["tenant_id"], current["customer_id"], invoice["package_id"], current["id"]
        )
    conn.execute(
        "UPDATE payment_attempts SET status='paid',provider_transaction_id=COALESCE(?,provider_transaction_id),updated_at=? WHERE payment_id=? AND tenant_id=?",
        (transaction_id or None, stamp, current["id"], current["tenant_id"]),
    )
    audit(conn, None, "payment_verified", "payment", current["id"], {
        "provider": provider, "provider_transaction_id": transaction_id, "subscription_id": subscription_id
    })
    return {"status": "paid", "subscription_id": subscription_id, "already_paid": False}


def csrf_check(request: Request) -> None:
    expected = request.session.get("csrf_token")
    supplied = request.headers.get("x-csrf-token")
    if not expected or not supplied or not hmac.compare_digest(str(expected), str(supplied)):
        raise HTTPException(403, "Security token expired. Refresh the page and try again.")


def current_user(request: Request) -> dict:
    sid = request.session.get("sid")
    if not sid:
        raise HTTPException(401, "Please sign in.")
    sid_hash = hashlib.sha256(sid.encode()).hexdigest()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT u.*, t.name AS tenant_name, t.slug AS tenant_slug, t.status AS tenant_status, t.brand_name, t.brand_primary "
            "FROM auth_sessions s JOIN users u ON u.id=s.user_id LEFT JOIN tenants t ON t.id=u.tenant_id "
            "WHERE s.id_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'",
            (sid_hash, now_iso()),
        ).fetchone()
    if not row:
        request.session.clear()
        raise HTTPException(401, "Session expired. Please sign in again.")
    user = dict(row)
    if user.get("tenant_id") and user.get("tenant_status") not in ("active", "trial", "past_due"):
        request.session.clear()
        raise HTTPException(403, "This ISP workspace is suspended. Contact its administrator.")
    return user


def need_roles(*roles: str):
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "You do not have permission to perform this action.")
        return user
    return dependency


def tenant_user(user: dict) -> str:
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "This action requires an ISP workspace.")
    return tenant_id


def tenant_plan(conn, tenant_id: str) -> dict:
    row = conn.execute("SELECT p.*,s.status subscription_status FROM tenant_subscriptions s JOIN saas_plans p ON p.code=s.plan_code WHERE s.tenant_id=?", (tenant_id,)).fetchone()
    if row:
        return dict(row)
    row = conn.execute("SELECT p.* FROM tenants t JOIN saas_plans p ON lower(p.name)=lower(t.plan) WHERE t.id=?", (tenant_id,)).fetchone()
    return dict(row) if row else {"code": "starter", "max_customers": 500, "max_routers": 3, "features_json": '{"hotspot":true,"pppoe":false,"agents":false}'}


def require_plan_feature(conn, tenant_id: str, feature: str) -> dict:
    plan = tenant_plan(conn, tenant_id)
    features = json.loads(plan.get("features_json") or "{}")
    if not features.get(feature, False):
        raise HTTPException(402, f"The {plan.get('name', plan.get('code', 'current'))} RIS plan does not include {feature.replace('_', ' ')}. Upgrade the ISP workspace plan.")
    return plan


def enforce_plan_limit(conn, tenant_id: str, resource: str) -> None:
    plan = tenant_plan(conn, tenant_id)
    limit_key = {"customers": "max_customers", "routers": "max_routers"}.get(resource)
    if not limit_key:
        return
    limit = int(plan.get(limit_key) or 0)
    if limit <= 0:
        return
    count = conn.execute(f"SELECT COUNT(*) n FROM {resource} WHERE tenant_id=?", (tenant_id,)).fetchone()["n"]
    if int(count) >= limit:
        raise HTTPException(402, f"Your RIS plan allows {limit:,} {resource}. Upgrade your plan to add more.")


def create_session(request: Request, conn: sqlite3.Connection, user_id: str) -> None:
    raw_sid = secrets.token_urlsafe(40)
    request.session.clear()
    request.session["sid"] = raw_sid
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO auth_sessions(id_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
        (hashlib.sha256(raw_sid.encode()).hexdigest(), user_id, (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(), now_iso()),
    )
    conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now_iso(), user_id))


def send_email_otp(to_email: str, code: str) -> None:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    if not password:
        raise RuntimeError("Gmail App Password is not configured.")
    msg = EmailMessage()
    msg["Subject"] = "Your RIS verification code"
    msg["From"] = os.getenv("SMTP_FROM", username)
    msg["To"] = to_email
    msg.set_content(f"Your RIS verification code is {code}. It expires in {OTP_TTL_MINUTES} minutes. Do not share it.")
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=20) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(msg)


def send_sms_otp(phone: str, code: str) -> None:
    api_key = os.getenv("AT_API_KEY", "")
    if not api_key:
        raise RuntimeError("Africa's Talking API key is not configured.")
    payload = {
        "username": os.getenv("AT_USERNAME", "sandbox"),
        "to": phone,
        "message": f"RIS verification code: {code}. Expires in {OTP_TTL_MINUTES} minutes. Do not share it.",
    }
    sender = os.getenv("AT_SENDER_ID", "")
    if sender:
        payload["from"] = sender
    response = requests.post(
        os.getenv("AT_SMS_URL", "https://api.africastalking.com/version1/messaging"),
        data=payload,
        headers={"apiKey": api_key, "Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    recipients = response.json().get("SMSMessageData", {}).get("Recipients", [])
    if not recipients or str(recipients[0].get("statusCode")) not in ("100", "Success"):
        raise RuntimeError("SMS provider did not confirm message acceptance.")


def log_otp_delivery(challenge_id: str, channel: str, destination: str, provider: str, status: str, detail: str = "") -> None:
    # Delivery audit records never contain the raw OTP or message body.
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO otp_delivery_logs(id,challenge_id,channel,destination,provider,status,detail,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (new_id("MSG"), challenge_id, channel, destination, provider, status, detail[:240], now_iso()),
        )


def deliver_codes(challenge_id: str, email: str, phone: str, email_code: str, sms_code: str) -> dict:
    delivered = {"email": False, "sms": False}
    errors = {}
    try:
        send_email_otp(email, email_code)
        delivered["email"] = True
        log_otp_delivery(challenge_id, "email", email, "gmail_smtp", "accepted", "SMTP server accepted the email.")
    except Exception as exc:
        errors["email"] = str(exc)
        log_otp_delivery(challenge_id, "email", email, "gmail_smtp", "development_preview" if DEV_SHOW_OTP else "failed", str(exc))
    try:
        send_sms_otp(phone, sms_code)
        delivered["sms"] = True
        log_otp_delivery(challenge_id, "sms", phone, "africas_talking", "accepted", "SMS provider accepted the message.")
    except Exception as exc:
        errors["sms"] = str(exc)
        log_otp_delivery(challenge_id, "sms", phone, "africas_talking", "development_preview" if DEV_SHOW_OTP else "failed", str(exc))
    if errors and ENVIRONMENT == "production":
        raise RuntimeError("OTP delivery failed. Check your email/SMS provider configuration.")
    if errors and not DEV_SHOW_OTP:
        raise RuntimeError("OTP delivery is incomplete. Configure Gmail SMTP and Africa's Talking.")
    return {"delivered": delivered, "debug": bool(errors and DEV_SHOW_OTP), "errors": errors}


def start_challenge(purpose: str, email: str, phone: str, payload: dict, tenant_id: str | None = None) -> dict:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "Enter a valid email address.")
    if not re.fullmatch(r"\+\d{10,15}", phone):
        raise HTTPException(400, "Enter a phone number in international format, such as +2567XXXXXXXX.")
    with db_conn() as conn:
        recent = conn.execute("SELECT COUNT(*) n FROM otp_challenges WHERE email=? AND created_at>?", (email, (datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())).fetchone()["n"]
        if recent >= 5:
            raise HTTPException(429, "Too many verification attempts for this email. Try again later.")
        cid = uuid.uuid4().hex
        email_code = f"{secrets.randbelow(900000) + 100000:06d}"
        sms_code = f"{secrets.randbelow(900000) + 100000:06d}"
        created = datetime.now(timezone.utc)
        expires = (created + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
        conn.execute(
            "INSERT INTO otp_challenges(id,purpose,tenant_id,email,phone,payload_json,email_hash,sms_hash,attempts,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,0,?,?)",
            (cid, purpose, tenant_id, email, phone, json.dumps(payload), otp_digest(email_code, cid, "email"), otp_digest(sms_code, cid, "sms"), expires, created.isoformat()),
        )
    try:
        delivery = deliver_codes(cid, email, phone, email_code, sms_code)
    except Exception:
        with db_conn() as conn:
            conn.execute("DELETE FROM otp_challenges WHERE id=?", (cid,))
        raise HTTPException(502, "Could not deliver both verification codes. Check the email and SMS settings.")
    response = {
        "success": True,
        "challenge_id": cid,
        "expires_in_minutes": OTP_TTL_MINUTES,
        "delivery": delivery["delivered"],
        "message": "Verification codes have been sent separately to your email and phone.",
    }
    if delivery["debug"]:
        response["development_only_codes"] = {"email": email_code, "sms": sms_code}
        response["development_notice"] = "Local development only. Codes are not being sent by every configured provider. This field is disabled in production."
    return response


def verify_challenge(challenge_id: str, email_code: str, sms_code: str, expected_purpose: str) -> dict:
    if not re.fullmatch(r"\d{6}", email_code) or not re.fullmatch(r"\d{6}", sms_code):
        raise HTTPException(400, "Enter both six-digit verification codes.")
    error: tuple[int, str] | None = None
    result: dict | None = None
    now = datetime.now(timezone.utc)
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM otp_challenges WHERE id=? AND purpose=?", (challenge_id, expected_purpose)).fetchone()
        if not row:
            error = (404, "Registration challenge not found. Start again.")
        elif datetime.fromisoformat(row["expires_at"]) < now:
            conn.execute("DELETE FROM otp_challenges WHERE id=?", (challenge_id,))
            error = (410, "Verification codes expired. Start registration again.")
        elif row["attempts"] >= OTP_MAX_ATTEMPTS:
            conn.execute("DELETE FROM otp_challenges WHERE id=?", (challenge_id,))
            error = (429, "Too many incorrect attempts. Start registration again.")
        else:
            good_email = hmac.compare_digest(row["email_hash"], otp_digest(email_code, challenge_id, "email"))
            good_sms = hmac.compare_digest(row["sms_hash"], otp_digest(sms_code, challenge_id, "sms"))
            if not (good_email and good_sms):
                # Do not raise while inside db_conn(): the context manager would roll back
                # the counter update. Commit the failed-attempt increment before responding.
                conn.execute("UPDATE otp_challenges SET attempts=attempts+1 WHERE id=?", (challenge_id,))
                error = (400, "One or both verification codes are incorrect.")
            else:
                result = {"row": dict(row), "payload": json.loads(row["payload_json"])}
    if error:
        raise HTTPException(error[0], error[1])
    if not result:
        raise HTTPException(400, "Could not verify registration codes.")
    return result


# ---------------------------------------------------------------------------
# Startup and static frontend
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/", include_in_schema=False)
@app.get("/super-admin", include_in_schema=False)
@app.get("/portal", include_in_schema=False)
@app.get("/portal/{tenant_slug}", include_in_schema=False)
def index(tenant_slug: str | None = None):
    return FileResponse(PROJECT_DIR / "index.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def pwa_manifest():
    return FileResponse(PROJECT_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js", include_in_schema=False)
def pwa_service_worker():
    return FileResponse(PROJECT_DIR / "service-worker.js", media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/offline.html", include_in_schema=False)
def offline_page():
    return FileResponse(PROJECT_DIR / "offline.html")


app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")


@app.get("/api/health")
def health():
    with db_conn() as conn:
        conn.execute("SELECT 1")
    return {"success": True, "status": "online", "product": "RIS Multi-tenant ISP SaaS", "environment": ENVIRONMENT, "database": "connected", "database_engine": "postgresql" if DATABASE_URL else "sqlite", "worker": "separate process required"}


@app.get("/api/csrf")
def csrf_token(request: Request):
    token = request.session.get("csrf_token") or secrets.token_urlsafe(32)
    request.session["csrf_token"] = token
    return {"csrf_token": token}


# ---------------------------------------------------------------------------
# Account registration: ISP workspace owners and tenant customers
# ---------------------------------------------------------------------------
@app.post("/api/auth/register/isp/start")
def register_isp_start(request: Request, data: dict):
    csrf_check(request)
    name = str(data.get("isp_name", "")).strip()
    owner = str(data.get("full_name", "")).strip()
    email = normalize_email(data.get("email"))
    phone = normalize_phone(data.get("phone"))
    password = str(data.get("password", ""))
    slug = slugify(str(data.get("workspace", "") or name))
    if len(name) < 2 or len(owner) < 2:
        raise HTTPException(400, "Enter the ISP/business name and account owner's full name.")
    if len(slug) < 3:
        raise HTTPException(400, "Workspace URL must contain at least three letters or numbers.")
    if len(password) < 12:
        raise HTTPException(400, "Use a password with at least 12 characters.")
    with db_conn() as conn:
        if conn.execute("SELECT 1 FROM tenants WHERE slug=?", (slug,)).fetchone():
            raise HTTPException(409, "That workspace URL is already taken.")
        if conn.execute("SELECT 1 FROM users WHERE tenant_id IS NULL AND lower(email)=?", (email,)).fetchone():
            raise HTTPException(409, "This email already belongs to a platform account.")
    payload = {"isp_name": name, "workspace": slug, "full_name": owner, "password_hash": hash_password(password)}
    return start_challenge("isp_owner", email, phone, payload)


@app.post("/api/auth/register/isp/verify")
def register_isp_verify(request: Request, data: dict):
    csrf_check(request)
    challenge = verify_challenge(str(data.get("challenge_id", "")), str(data.get("email_code", "")), str(data.get("sms_code", "")), "isp_owner")
    row, payload = challenge["row"], challenge["payload"]
    tenant_id, user_id = new_id("TEN"), new_id("USR")
    now = datetime.now(timezone.utc)
    trial_end = (now + timedelta(days=14)).isoformat()
    try:
        with db_conn() as conn:
            if conn.execute("SELECT 1 FROM tenants WHERE slug=?", (payload["workspace"],)).fetchone():
                raise HTTPException(409, "Workspace was registered by someone else. Start again with another workspace name.")
            conn.execute("INSERT INTO tenants(id,name,slug,email,phone,status,plan,brand_name,trial_ends_at,created_at) VALUES(?,?,?,?,?,'trial','Starter',?,?,?)",
                         (tenant_id, payload["isp_name"], payload["workspace"], row["email"], row["phone"], payload["isp_name"], trial_end, now.isoformat()))
            conn.execute("INSERT INTO users(id,tenant_id,full_name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,'owner','active',?)",
                         (user_id, tenant_id, payload["full_name"], row["email"], row["phone"], payload["password_hash"], now.isoformat()))
            portal_config = {"headline": f"Welcome to {payload['isp_name']}", "welcome_message": "Choose an internet package or enter your voucher to get connected.", "primary_color": "#087bd1", "background_color": "#071a2e", "footer_text": "Powered by RIS", "show_registration": True, "show_packages": True, "show_voucher": True}
            conn.execute("INSERT INTO captive_portals(id,tenant_id,enabled,config_json,created_at,updated_at) VALUES(?,?,1,?,?,?)", (new_id("CPT"), tenant_id, json.dumps(portal_config), now_iso(), now_iso()))
            conn.execute("INSERT INTO tenant_subscriptions(id,tenant_id,plan_code,status,billing_cycle,period_start,period_end,trial_ends_at,next_invoice_at,created_at,updated_at) VALUES(?,?, 'starter','trial','monthly',?,?,?,?,?,?)",
                         (new_id("SAS"), tenant_id, now.isoformat(), trial_end, trial_end, trial_end, now_iso(), now_iso()))
            pkg_id = new_id("PKG")
            conn.execute("INSERT INTO packages(id,tenant_id,name,service_type,price_minor,currency,validity_hours,data_limit_mb,speed_down_kbps,speed_up_kbps,device_limit,active,created_at) VALUES(?,?,?,'hotspot',3000,'UGX',24,2048,2000,1000,1,1,?)",
                         (pkg_id, tenant_id, "Starter 2GB Daily", now.isoformat()))
            conn.execute("DELETE FROM otp_challenges WHERE id=?", (data["challenge_id"],))
            audit(conn, None, "tenant_registered", "tenant", tenant_id, {"slug": payload["workspace"]})
            create_session(request, conn, user_id)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email or phone already exists in this workspace.")
    return {"success": True, "message": "ISP workspace created. Your 14-day trial has started.", "tenant": {"id": tenant_id, "name": payload["isp_name"], "slug": payload["workspace"], "status": "trial"}}


@app.post("/api/auth/register/customer/start")
def register_customer_start(request: Request, data: dict):
    csrf_check(request)
    tenant_slug = slugify(str(data.get("tenant_slug", "")))
    name, email = str(data.get("full_name", "")).strip(), normalize_email(data.get("email"))
    phone, password = normalize_phone(data.get("phone")), str(data.get("password", ""))
    if len(name) < 2 or len(password) < 12:
        raise HTTPException(400, "Enter your full name and a password of at least 12 characters.")
    with db_conn() as conn:
        tenant = conn.execute("SELECT id,status FROM tenants WHERE slug=?", (tenant_slug,)).fetchone()
        if not tenant or tenant["status"] not in ("active", "trial"):
            raise HTTPException(404, "ISP workspace not found or not accepting registrations.")
        if conn.execute("SELECT 1 FROM users WHERE tenant_id=? AND (lower(email)=? OR phone=?)", (tenant["id"], email, phone)).fetchone():
            raise HTTPException(409, "An account with this email or phone already exists. Please sign in.")
    payload = {"tenant_slug": tenant_slug, "full_name": name, "password_hash": hash_password(password)}
    return start_challenge("customer", email, phone, payload, tenant["id"])


@app.post("/api/auth/register/customer/verify")
def register_customer_verify(request: Request, data: dict):
    csrf_check(request)
    challenge = verify_challenge(str(data.get("challenge_id", "")), str(data.get("email_code", "")), str(data.get("sms_code", "")), "customer")
    row, payload = challenge["row"], challenge["payload"]
    user_id, customer_id = new_id("USR"), new_id("CUS")
    try:
        with db_conn() as conn:
            conn.execute("INSERT INTO users(id,tenant_id,full_name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,'customer','active',?)",
                         (user_id, row["tenant_id"], payload["full_name"], row["email"], row["phone"], payload["password_hash"], now_iso()))
            conn.execute("INSERT INTO customers(id,tenant_id,user_id,name,email,phone,status,service_type,created_at) VALUES(?,?,?,?,?,?,'active','hotspot',?)",
                         (customer_id, row["tenant_id"], user_id, payload["full_name"], row["email"], row["phone"], now_iso()))
            conn.execute("DELETE FROM otp_challenges WHERE id=?", (data["challenge_id"],))
            audit(conn, {"tenant_id": row["tenant_id"], "id": user_id}, "customer_self_registered", "customer", customer_id)
            create_session(request, conn, user_id)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email or phone already exists. Please sign in.")
    return {"success": True, "message": "Your customer account has been created and verified.", "customer_id": customer_id}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
def login(request: Request, data: dict):
    csrf_check(request)
    login_identifier = str(data.get("email", data.get("username", ""))).strip()
    email = normalize_email(login_identifier)
    password = str(data.get("password", ""))
    tenant_slug = slugify(str(data.get("tenant_slug", ""))) if data.get("tenant_slug") else ""
    with db_conn() as conn:
        if tenant_slug:
            tenant = conn.execute("SELECT id FROM tenants WHERE slug=?", (tenant_slug,)).fetchone()
            if not tenant:
                raise HTTPException(401, "Workspace not found. Check the ISP workspace name.")
            row = conn.execute("SELECT * FROM users WHERE tenant_id=? AND lower(email)=?", (tenant["id"], email)).fetchone()
        elif "@" in email:
            row = conn.execute("SELECT * FROM users WHERE tenant_id IS NULL AND lower(email)=?", (email,)).fetchone()
        else:
            # The platform owner may sign in with the configured display name.
            # ISP staff and customers must continue using their email + workspace.
            row = conn.execute("SELECT * FROM users WHERE tenant_id IS NULL AND role='platform_admin' AND lower(full_name)=lower(?)", (login_identifier,)).fetchone()
        if not row or not verify_password(password, row["password_hash"]) or row["status"] != "active":
            raise HTTPException(401, "Email, password or workspace is incorrect.")
        create_session(request, conn, row["id"])
        audit(conn, dict(row), "login", "user", row["id"])
    return {"success": True, "user": safe_user(row)}


@app.post("/api/auth/logout")
def logout(request: Request, user: dict = Depends(current_user)):
    csrf_check(request)
    sid = request.session.get("sid", "")
    with db_conn() as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE id_hash=?", (now_iso(), hashlib.sha256(sid.encode()).hexdigest()))
        audit(conn, user, "logout", "user", user["id"])
    request.session.clear()
    return {"success": True}


@app.post("/api/auth/change-password")
def change_password(request: Request, data: dict, user: dict = Depends(current_user)):
    csrf_check(request)
    current = str(data.get("current_password", ""))
    new_password = str(data.get("new_password", ""))
    if len(new_password) < 12:
        raise HTTPException(400, "New password must contain at least 12 characters.")
    if current == new_password:
        raise HTTPException(400, "Choose a different password.")
    sid = request.session.get("sid", "")
    sid_hash = hashlib.sha256(sid.encode()).hexdigest()
    with db_conn() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if not row or not verify_password(current, row["password_hash"]):
            raise HTTPException(400, "Current password is incorrect.")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user["id"]))
        conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE user_id=? AND id_hash<>? AND revoked_at IS NULL", (now_iso(), user["id"], sid_hash))
        audit(conn, user, "password_changed", "user", user["id"])
    return {"success": True, "message": "Password updated. Other active sessions have been signed out."}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    result = safe_user(user)
    if user.get("tenant_id"):
        result["tenant"] = {"id": user["tenant_id"], "name": user.get("tenant_name"), "slug": user.get("tenant_slug"), "status": user.get("tenant_status"), "brand_name": user.get("brand_name"), "brand_primary": user.get("brand_primary")}
    return {"success": True, "user": result}


# ---------------------------------------------------------------------------
# SaaS platform administration
# ---------------------------------------------------------------------------
@app.get("/api/platform/tenants")
def platform_tenants(user: dict = Depends(need_roles("platform_admin"))):
    with db_conn() as conn:
        rows = conn.execute("SELECT t.*, (SELECT COUNT(*) FROM users u WHERE u.tenant_id=t.id) AS users_count, (SELECT COUNT(*) FROM customers c WHERE c.tenant_id=t.id) AS customers_count FROM tenants t ORDER BY created_at DESC").fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.get("/api/platform/customers")
def platform_customers(user: dict = Depends(need_roles("platform_admin")), tenant_id: str = "", q: str = "", status: str = "", include_archived: bool = False):
    clauses = []
    params: list[Any] = []
    if tenant_id:
        clauses.append("c.tenant_id=?")
        params.append(tenant_id)
    if not include_archived:
        clauses.append("c.status<>'archived'")
    if status:
        clauses.append("c.status=?")
        params.append(status)
    if q.strip():
        needle=f"%{q.strip()[:100]}%"
        clauses.append("(c.name LIKE ? OR c.email LIKE ? OR c.phone LIKE ? OR c.id LIKE ? OR t.name LIKE ? OR t.slug LIKE ?)")
        params.extend([needle,needle,needle,needle,needle,needle])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with db_conn() as conn:
        rows = conn.execute("SELECT c.*,t.name tenant_name,t.slug tenant_slug,p.name package_name,(SELECT COUNT(*) FROM payments pm WHERE pm.customer_id=c.id AND pm.tenant_id=c.tenant_id) payment_count,(SELECT MAX(s.expires_at) FROM subscriptions s WHERE s.customer_id=c.id AND s.tenant_id=c.tenant_id) latest_expiry,(SELECT na.provision_status FROM network_accounts na WHERE na.customer_id=c.id AND na.tenant_id=c.tenant_id LIMIT 1) provision_status FROM customers c JOIN tenants t ON t.id=c.tenant_id LEFT JOIN packages p ON p.id=c.package_id AND p.tenant_id=c.tenant_id" + where + " ORDER BY c.created_at DESC LIMIT 1500", params).fetchall()
        tenants = conn.execute("SELECT id,name,slug,status FROM tenants ORDER BY name").fetchall()
    return {"success": True, "items": [dict(r) for r in rows], "tenants": [dict(t) for t in tenants]}


@app.post("/api/platform/customers")
def platform_add_customer(request: Request, data: dict, user: dict = Depends(need_roles("platform_admin"))):
    csrf_check(request)
    tenant_id = str(data.get("tenant_id", "")).strip()
    name = str(data.get("name", "")).strip()
    email = normalize_email(data.get("email"))
    phone = normalize_phone(data.get("phone"))
    service_type = str(data.get("service_type", "hotspot")).lower()
    if not tenant_id or len(name) < 2:
        raise HTTPException(400, "Select an ISP workspace and enter a valid customer name.")
    if service_type not in ("hotspot", "pppoe"):
        raise HTTPException(400, "Service type must be hotspot or pppoe.")
    cid = new_id("CUS")
    with db_conn() as conn:
        tenant = conn.execute("SELECT id FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        if not tenant:
            raise HTTPException(404, "ISP workspace not found.")
        enforce_plan_limit(conn, tenant_id, "customers")
        if service_type == "pppoe":
            require_plan_feature(conn, tenant_id, "pppoe")
        try:
            conn.execute("INSERT INTO customers(id,tenant_id,name,email,phone,address,status,service_type,created_at) VALUES(?,?,?,?,?,?,'pending',?,?)", (cid,tenant_id,name,email,phone,str(data.get("address", "")).strip()[:300],service_type,now_iso()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "A customer with this email or phone already exists in this ISP workspace.")
        conn.execute("INSERT INTO audit_logs(id,tenant_id,actor_id,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (new_id("LOG"),tenant_id,user["id"],"platform_customer_created","customer",cid,json.dumps({"platform_admin": True}),now_iso()))
    return {"success": True, "id": cid, "message": "Customer record created in the selected ISP workspace."}


@app.patch("/api/platform/customers/{customer_id}")
def platform_update_customer(customer_id: str, request: Request, data: dict, user: dict = Depends(need_roles("platform_admin"))):
    csrf_check(request)
    with db_conn() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            raise HTTPException(404, "Customer not found.")
        status = str(data.get("status", customer["status"])).lower()
        if status not in ("active", "suspended", "pending", "archived"):
            raise HTTPException(400, "Invalid customer status.")
        conn.execute("UPDATE customers SET status=? WHERE id=?", (status,customer_id))
        if status in ("suspended", "archived", "active"):
            set_customer_network_state(conn, customer["tenant_id"], customer_id, status)
        conn.execute("INSERT INTO audit_logs(id,tenant_id,actor_id,action,entity,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)", (new_id("LOG"),customer["tenant_id"],user["id"],"platform_customer_status_changed","customer",customer_id,json.dumps({"status":status}),now_iso()))
    return {"success": True, "message": "Customer status updated."}


@app.patch("/api/platform/tenants/{tenant_id}/status")
def platform_tenant_status(tenant_id: str, request: Request, data: dict, user: dict = Depends(need_roles("platform_admin"))):
    csrf_check(request)
    status = str(data.get("status", ""))
    if status not in ("active", "suspended", "trial"):
        raise HTTPException(400, "Status must be active, trial or suspended.")
    with db_conn() as conn:
        cur = conn.execute("UPDATE tenants SET status=? WHERE id=?", (status, tenant_id))
        if not cur.rowcount:
            raise HTTPException(404, "ISP workspace not found.")
        audit(conn, user, "tenant_status_changed", "tenant", tenant_id, {"status": status})
    return {"success": True, "status": status}


# ---------------------------------------------------------------------------
# Tenant dashboard and business settings
# ---------------------------------------------------------------------------
@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    if user["role"] == "platform_admin":
        with db_conn() as conn:
            total = conn.execute("SELECT COUNT(*) n FROM tenants").fetchone()["n"]
            active = conn.execute("SELECT COUNT(*) n FROM tenants WHERE status='active'").fetchone()["n"]
            trials = conn.execute("SELECT COUNT(*) n FROM tenants WHERE status='trial'").fetchone()["n"]
            suspended = conn.execute("SELECT COUNT(*) n FROM tenants WHERE status='suspended'").fetchone()["n"]
        return {"success": True, "scope": "platform", "summary": {"tenants": total, "active_tenants": active, "trials": trials, "suspended": suspended}}
    tid = tenant_user(user)
    with db_conn() as conn:
        customers = conn.execute("SELECT COUNT(*) n FROM customers WHERE tenant_id=?", (tid,)).fetchone()["n"]
        active_customers = conn.execute("SELECT COUNT(*) n FROM customers WHERE tenant_id=? AND status='active'", (tid,)).fetchone()["n"]
        packages = conn.execute("SELECT COUNT(*) n FROM packages WHERE tenant_id=? AND active=1", (tid,)).fetchone()["n"]
        vouchers = conn.execute("SELECT COUNT(*) n FROM vouchers WHERE tenant_id=? AND status='unused'", (tid,)).fetchone()["n"]
        money = conn.execute("SELECT COUNT(*) n,COALESCE(SUM(amount_minor),0) total FROM payments WHERE tenant_id=? AND status='paid'", (tid,)).fetchone()
        pending = conn.execute("SELECT COUNT(*) n,COALESCE(SUM(amount_minor),0) total FROM payments WHERE tenant_id=? AND status='pending'", (tid,)).fetchone()
        recent = conn.execute("SELECT p.id,p.reference,p.amount_minor,p.currency,p.status,p.created_at,c.name customer_name FROM payments p JOIN customers c ON c.id=p.customer_id AND c.tenant_id=p.tenant_id WHERE p.tenant_id=? ORDER BY p.created_at DESC LIMIT 6", (tid,)).fetchall()
    return {"success": True, "scope": "tenant", "summary": {"customers": customers, "active_customers": active_customers, "active_packages": packages, "unused_vouchers": vouchers, "revenue_minor": money["total"], "successful_payments": money["n"], "pending_payments": pending["n"], "pending_minor": pending["total"]}, "recent_payments": [dict(x) for x in recent]}


@app.get("/api/tenant/settings")
def tenant_settings(user: dict = Depends(current_user)):
    tid = tenant_user(user)
    with db_conn() as conn:
        row = conn.execute("SELECT id,name,slug,email,phone,status,plan,brand_name,brand_primary,custom_domain,currency,timezone,trial_ends_at,created_at FROM tenants WHERE id=?", (tid,)).fetchone()
    return {"success": True, "tenant": dict(row)}


@app.patch("/api/tenant/settings")
def update_tenant_settings(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    allowed = {"brand_name", "brand_primary", "custom_domain", "name"}
    fields = {k: str(data[k]).strip() for k in allowed if k in data}
    if "brand_primary" in fields and not re.fullmatch(r"#[0-9a-fA-F]{6}", fields["brand_primary"]):
        raise HTTPException(400, "Brand colour must be a six-digit hex colour.")
    if not fields:
        raise HTTPException(400, "No settings supplied.")
    with db_conn() as conn:
        conn.execute("UPDATE tenants SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?", [*fields.values(), tid])
        audit(conn, user, "tenant_settings_updated", "tenant", tid, fields)
    return {"success": True}


# ---------------------------------------------------------------------------
# Customers and packages
# ---------------------------------------------------------------------------
@app.get("/api/customers")
def list_customers(user: dict = Depends(need_roles("owner", "admin", "finance", "support", "network_admin")), q: str = "", status: str = "", include_archived: bool = False):
    tid = tenant_user(user)
    clauses = ["c.tenant_id=?"]
    params: list[Any] = [tid]
    if not include_archived:
        clauses.append("c.status<>'archived'")
    if status:
        clauses.append("c.status=?")
        params.append(status)
    if q.strip():
        needle = f"%{q.strip()[:100]}%"
        clauses.append("(c.name LIKE ? OR c.email LIKE ? OR c.phone LIKE ? OR c.id LIKE ?)")
        params.extend([needle, needle, needle, needle])
    with db_conn() as conn:
        rows = conn.execute("SELECT c.*,p.name package_name,(SELECT COUNT(*) FROM payments pm WHERE pm.customer_id=c.id AND pm.tenant_id=c.tenant_id) payment_count,(SELECT MAX(s.expires_at) FROM subscriptions s WHERE s.customer_id=c.id AND s.tenant_id=c.tenant_id) latest_expiry,(SELECT na.provision_status FROM network_accounts na WHERE na.customer_id=c.id AND na.tenant_id=c.tenant_id LIMIT 1) provision_status FROM customers c LEFT JOIN packages p ON p.id=c.package_id AND p.tenant_id=c.tenant_id WHERE " + " AND ".join(clauses) + " ORDER BY c.created_at DESC LIMIT 1000", params).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.post("/api/customers")
def add_customer(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "support"))):
    csrf_check(request)
    tid = tenant_user(user)
    name = str(data.get("name", "")).strip()
    email = normalize_email(data.get("email"))
    phone = normalize_phone(data.get("phone"))
    if len(name) < 2:
        raise HTTPException(400, "Customer name is required.")
    service_type = str(data.get("service_type", "hotspot")).lower()
    status = str(data.get("status", "active")).lower()
    package_id = str(data.get("package_id") or "").strip() or None
    if service_type not in ("hotspot", "pppoe"):
        raise HTTPException(400, "Service type must be hotspot or pppoe.")
    if status not in ("active", "suspended", "pending"):
        raise HTTPException(400, "Customer status must be active, suspended or pending.")
    cid = new_id("CUS")
    try:
        with db_conn() as conn:
            enforce_plan_limit(conn, tid, "customers")
            if package_id:
                package = conn.execute("SELECT service_type FROM packages WHERE id=? AND tenant_id=?", (package_id, tid)).fetchone()
                if not package:
                    raise HTTPException(404, "Package not found in this ISP workspace.")
                if package["service_type"] != service_type:
                    raise HTTPException(400, "The selected package does not match the customer's service type.")
            if service_type == "pppoe":
                require_plan_feature(conn, tid, "pppoe")
            conn.execute("INSERT INTO customers(id,tenant_id,name,email,phone,address,service_type,status,package_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                         (cid, tid, name, email, phone, str(data.get("address", "")).strip(), service_type, status, package_id, now_iso()))
            audit(conn, user, "customer_created", "customer", cid)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A customer with this email or phone already exists in this ISP workspace.")
    return {"success": True, "id": cid}


@app.patch("/api/customers/{customer_id}")
def update_customer(customer_id: str, request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "support"))):
    csrf_check(request)
    tid = tenant_user(user)
    allowed_statuses = {"active", "suspended", "pending"}
    with db_conn() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE id=? AND tenant_id=? AND status<>'archived'", (customer_id, tid)).fetchone()
        if not customer:
            raise HTTPException(404, "Customer not found in this ISP workspace.")
        name = str(data.get("name", customer["name"])).strip()
        email = normalize_email(data.get("email", customer["email"]))
        phone = normalize_phone(data.get("phone", customer["phone"]))
        address = str(data.get("address", customer["address"] or "")).strip()[:300]
        status = str(data.get("status", customer["status"])).lower()
        service_type = str(data.get("service_type", customer["service_type"])).lower()
        package_id = str(data.get("package_id", customer["package_id"] or "")).strip() or None
        if len(name) < 2:
            raise HTTPException(400, "Customer name must contain at least two characters.")
        if status not in allowed_statuses:
            raise HTTPException(400, "Customer status must be active, suspended or pending.")
        if service_type not in ("hotspot", "pppoe"):
            raise HTTPException(400, "Service type must be hotspot or pppoe.")
        if package_id:
            package = conn.execute("SELECT service_type FROM packages WHERE id=? AND tenant_id=?", (package_id, tid)).fetchone()
            if not package:
                raise HTTPException(404, "Package not found in this ISP workspace.")
            if package["service_type"] != service_type:
                raise HTTPException(400, "The selected package does not match the customer's service type.")
        if service_type == "pppoe":
            require_plan_feature(conn, tid, "pppoe")
        try:
            conn.execute("UPDATE customers SET name=?,email=?,phone=?,address=?,status=?,service_type=?,package_id=? WHERE id=? AND tenant_id=?", (name,email,phone,address,status,service_type,package_id,customer_id,tid))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Another customer already uses this email or phone number.")
        if status in ("suspended", "active") or package_id != customer["package_id"]:
            set_customer_network_state(conn, tid, customer_id, status if status in ("suspended", "active") else "active")
        audit(conn, user, "customer_updated", "customer", customer_id, {"status": status, "service_type": service_type})
    return {"success": True, "message": "Customer details updated."}


@app.delete("/api/customers/{customer_id}")
def archive_customer(customer_id: str, request: Request, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        customer = conn.execute("SELECT id,status FROM customers WHERE id=? AND tenant_id=?", (customer_id, tid)).fetchone()
        if not customer:
            raise HTTPException(404, "Customer not found in this ISP workspace.")
        if customer["status"] == "archived":
            return {"success": True, "message": "Customer is already archived."}
        conn.execute("UPDATE customers SET status='archived' WHERE id=? AND tenant_id=?", (customer_id, tid))
        set_customer_network_state(conn, tid, customer_id, "archived")
        audit(conn, user, "customer_archived", "customer", customer_id, {"soft_delete": True})
    return {"success": True, "message": "Customer archived. Billing and audit history were preserved."}


@app.post("/api/customers/{customer_id}/restore")
def restore_customer(customer_id: str, request: Request, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        cur = conn.execute("UPDATE customers SET status='pending' WHERE id=? AND tenant_id=? AND status='archived'", (customer_id, tid))
        if not cur.rowcount:
            raise HTTPException(404, "Archived customer not found in this ISP workspace.")
        set_customer_network_state(conn, tid, customer_id, "suspended")
        audit(conn, user, "customer_restored_pending", "customer", customer_id)
    return {"success": True, "message": "Customer record restored as pending. Confirm a valid package/payment before reactivating internet access."}


@app.get("/api/packages")
def list_packages(user: dict = Depends(need_roles("owner", "admin", "finance", "support", "network_admin", "agent"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM packages WHERE tenant_id=? ORDER BY created_at DESC", (tid,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.post("/api/packages")
def add_package(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "finance"))):
    csrf_check(request)
    tid = tenant_user(user)
    name = str(data.get("name", "")).strip()
    try:
        price = int(round(float(data.get("price", 0))))
        validity = int(data.get("validity_hours", 24))
        quota = int(data.get("data_limit_mb", 0))
        down = int(data.get("speed_down_kbps", 0))
        up = int(data.get("speed_up_kbps", 0))
        devices = int(data.get("device_limit", 1))
    except (TypeError, ValueError):
        raise HTTPException(400, "Price, validity, limits and speeds must be numbers.")
    if len(name) < 2 or price < 0 or validity < 1 or min(quota, down, up) < 0 or devices < 1:
        raise HTTPException(400, "Check package name, price, validity and limits.")
    pid = new_id("PKG")
    service_type = str(data.get("service_type", "hotspot")).lower()
    if service_type not in ("hotspot", "pppoe"):
        raise HTTPException(400, "Service type must be hotspot or pppoe.")
    with db_conn() as conn:
        if service_type == "pppoe":
            require_plan_feature(conn, tid, "pppoe")
        conn.execute("INSERT INTO packages(id,tenant_id,name,service_type,price_minor,currency,validity_hours,data_limit_mb,speed_down_kbps,speed_up_kbps,device_limit,active,created_at) VALUES(?,?,?,?,?,'UGX',?,?,?,?,?,1,?)",
                     (pid, tid, name, service_type, price, validity, quota, down, up, devices, now_iso()))
        audit(conn, user, "package_created", "package", pid)
    return {"success": True, "id": pid}


@app.patch("/api/packages/{package_id}")
def update_package(package_id: str, request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "finance"))):
    csrf_check(request)
    tid = tenant_user(user)
    allowed = {"name", "active", "validity_hours", "data_limit_mb", "speed_down_kbps", "speed_up_kbps", "device_limit", "price_minor"}
    fields = {k: data[k] for k in allowed if k in data}
    if not fields:
        raise HTTPException(400, "No package fields supplied.")
    with db_conn() as conn:
        cur = conn.execute("UPDATE packages SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=? AND tenant_id=?", [*fields.values(), package_id, tid])
        if not cur.rowcount:
            raise HTTPException(404, "Package not found.")
        audit(conn, user, "package_updated", "package", package_id, fields)
    return {"success": True}


# ---------------------------------------------------------------------------
# Vouchers, agents, routers
# ---------------------------------------------------------------------------
@app.get("/api/vouchers")
def list_vouchers(user: dict = Depends(need_roles("owner", "admin", "finance", "agent"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT v.*,p.name package_name FROM vouchers v JOIN packages p ON p.id=v.package_id AND p.tenant_id=v.tenant_id WHERE v.tenant_id=? ORDER BY v.created_at DESC LIMIT 500", (tid,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.post("/api/vouchers/generate")
def generate_vouchers(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "agent"))):
    csrf_check(request)
    tid = tenant_user(user)
    try:
        count = int(data.get("count", 1))
    except (ValueError, TypeError):
        count = 0
    package_id = str(data.get("package_id", ""))
    if count < 1 or count > 1000:
        raise HTTPException(400, "Generate between 1 and 1,000 vouchers per batch.")
    batch_id = new_id("BATCH")
    created, codes = now_iso(), []
    with db_conn() as conn:
        if not conn.execute("SELECT 1 FROM packages WHERE id=? AND tenant_id=? AND active=1", (package_id, tid)).fetchone():
            raise HTTPException(404, "Active package not found in this workspace.")
        for _ in range(count):
            code = secrets.token_urlsafe(7).replace("-", "").replace("_", "").upper()[:10]
            conn.execute("INSERT INTO vouchers(code,tenant_id,package_id,batch_id,status,created_at) VALUES(?,?,?,?,'unused',?)", (code, tid, package_id, batch_id, created))
            codes.append(code)
        audit(conn, user, "vouchers_generated", "voucher_batch", batch_id, {"count": count, "package_id": package_id})
    return {"success": True, "batch_id": batch_id, "count": len(codes), "codes": codes}


@app.get("/api/routers")
def list_routers(user: dict = Depends(need_roles("owner", "admin", "network_admin", "support"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM routers WHERE tenant_id=? ORDER BY created_at DESC", (tid,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.post("/api/routers")
def add_router(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    name, host = str(data.get("name", "")).strip(), str(data.get("host", "")).strip()
    try:
        port = int(data.get("api_port", 8729))
    except (TypeError, ValueError):
        raise HTTPException(400, "Router API port must be a number.")
    if not name or not host or not 1 <= port <= 65535:
        raise HTTPException(400, "Router name, host and valid API port are required.")
    rid = new_id("RTR")
    with db_conn() as conn:
        enforce_plan_limit(conn, tid, "routers")
        conn.execute("INSERT INTO routers(id,tenant_id,name,host,api_port,site,status,created_at) VALUES(?,?,?,?,?,?,'unverified',?)",
                     (rid, tid, name, host, port, str(data.get("site", "")), now_iso()))
        audit(conn, user, "router_registered", "router", rid)
    return {"success": True, "id": rid, "note": "Router inventory record created. Add its RouterOS API-SSL credentials and run a connection test before using network actions."}


@app.put("/api/routers/{router_id}/credentials")
def save_router_credentials(router_id: str, request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        router = conn.execute("SELECT id FROM routers WHERE id=? AND tenant_id=?", (router_id, tid)).fetchone()
        if not router:
            raise HTTPException(404, "Router not found in this workspace.")
        prior = conn.execute("SELECT secrets_encrypted FROM router_secrets WHERE router_id=? AND tenant_id=?", (router_id, tid)).fetchone()
        secrets_data = decrypt_json(prior["secrets_encrypted"]) if prior else {}
        for key in ("api_username", "api_password", "radius_server", "radius_secret"):
            value = str(data.get(key, "")).strip()
            if value:
                secrets_data[key] = value
        if not secrets_data.get("api_username") or not secrets_data.get("api_password"):
            raise HTTPException(400, "RouterOS API username and password are required.")
        if prior:
            conn.execute("UPDATE router_secrets SET secrets_encrypted=?,updated_at=? WHERE router_id=? AND tenant_id=?", (encrypt_json(secrets_data), now_iso(), router_id, tid))
        else:
            conn.execute("INSERT INTO router_secrets(router_id,tenant_id,secrets_encrypted,updated_at) VALUES(?,?,?,?)", (router_id, tid, encrypt_json(secrets_data), now_iso()))
        audit(conn, user, "router_credentials_updated", "router", router_id)
    return {"success": True, "message": "Router credentials encrypted and saved. Secret values are never returned by the API."}


def router_api_connection(router: dict, secrets_data: dict):
    try:
        import routeros_api
    except ImportError as exc:
        raise RuntimeError("RouterOS API client is not installed. Install backend/requirements.txt.") from exc
    pool = routeros_api.RouterOsApiPool(
        router["host"], username=secrets_data["api_username"], password=secrets_data["api_password"],
        port=int(router["api_port"]), plaintext_login=True, use_ssl=True,
        ssl_verify=True, ssl_verify_hostname=True,
    )
    return pool, pool.get_api()


@app.post("/api/routers/{router_id}/test")
def test_router_connection(router_id: str, request: Request, user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        router = conn.execute("SELECT * FROM routers WHERE id=? AND tenant_id=?", (router_id, tid)).fetchone()
        saved = conn.execute("SELECT secrets_encrypted FROM router_secrets WHERE router_id=? AND tenant_id=?", (router_id, tid)).fetchone()
    if not router:
        raise HTTPException(404, "Router not found.")
    if not saved:
        raise HTTPException(400, "Save RouterOS API credentials first.")
    pool = None
    try:
        pool, api = router_api_connection(dict(router), decrypt_json(saved["secrets_encrypted"]))
        resource = api.get_resource("/system/resource").get()
        identity = api.get_resource("/system/identity").get()
        version = resource[0].get("version", "unknown") if resource else "unknown"
        name = identity[0].get("name", router["name"]) if identity else router["name"]
        with db_conn() as conn:
            conn.execute("UPDATE routers SET status='online',last_seen=? WHERE id=? AND tenant_id=?", (now_iso(), router_id, tid))
            audit(conn, user, "router_connection_tested", "router", router_id, {"version": version})
        return {"success": True, "status": "online", "identity": name, "version": version, "message": "RouterOS API-SSL connection verified."}
    except Exception as exc:
        with db_conn() as conn:
            conn.execute("UPDATE routers SET status='offline' WHERE id=? AND tenant_id=?", (router_id, tid))
        logger.warning("Router test failed for %s: %s", router_id, exc)
        raise HTTPException(502, "Router connection failed. Check host, API-SSL port, certificate, firewall and credentials.")
    finally:
        if pool:
            try: pool.disconnect()
            except Exception: pass


@app.get("/api/routers/{router_id}/status")
def router_live_status(router_id: str, user: dict = Depends(need_roles("owner", "admin", "network_admin", "support"))):
    """Read-only live RouterOS health and subscriber-session snapshot."""
    tid = tenant_user(user)
    with db_conn() as conn:
        router = conn.execute("SELECT * FROM routers WHERE id=? AND tenant_id=?", (router_id, tid)).fetchone()
        saved = conn.execute("SELECT secrets_encrypted FROM router_secrets WHERE router_id=? AND tenant_id=?", (router_id, tid)).fetchone()
    if not router:
        raise HTTPException(404, "Router not found in this workspace.")
    if not saved:
        raise HTTPException(400, "Save RouterOS API-SSL credentials before checking live status.")

    pool = None
    try:
        pool, api = router_api_connection(dict(router), decrypt_json(saved["secrets_encrypted"]))
        def get_rows(path):
            try:
                return api.get_resource(path).get()
            except Exception as exc:
                # Some routers have no Hotspot or PPP sessions configured. Treat
                # a missing menu as an empty service list, not a failed router.
                message = str(exc).lower()
                if "no such command" in message or "not found" in message or "no such item" in message:
                    return []
                raise
        resource_rows = get_rows("/system/resource")
        identity_rows = get_rows("/system/identity")
        hotspot_rows = get_rows("/ip/hotspot/active")
        ppp_rows = get_rows("/ppp/active")
        resource = resource_rows[0] if resource_rows else {}
        identity = identity_rows[0] if identity_rows else {}
        def safe_sessions(rows, service):
            return [{"service": service, "name": row.get("user", row.get("name", "")),
                     "address": row.get("address", ""), "uptime": row.get("uptime", ""),
                     "caller_id": row.get("mac-address", row.get("caller-id", ""))}
                    for row in rows]
        sessions = safe_sessions(hotspot_rows, "hotspot") + safe_sessions(ppp_rows, "pppoe")
        with db_conn() as conn:
            conn.execute("UPDATE routers SET status='online',last_seen=? WHERE id=? AND tenant_id=?", (now_iso(), router_id, tid))
            audit(conn, user, "router_live_status_read", "router", router_id,
                  {"hotspot_sessions": len(hotspot_rows), "pppoe_sessions": len(ppp_rows)})
        return {"success": True, "status": "online", "identity": identity.get("name", router["name"]),
                "version": resource.get("version", "unknown"), "uptime": resource.get("uptime", "unknown"),
                "cpu_load": resource.get("cpu-load"), "free_memory": resource.get("free-memory"),
                "total_memory": resource.get("total-memory"), "hotspot_sessions": len(hotspot_rows),
                "pppoe_sessions": len(ppp_rows), "sessions": sessions,
                "message": "Live RouterOS status read successfully. No router configuration was changed."}
    except Exception as exc:
        with db_conn() as conn:
            conn.execute("UPDATE routers SET status='offline' WHERE id=? AND tenant_id=?", (router_id, tid))
        logger.warning("Router live status failed for %s: %s", router_id, exc)
        raise HTTPException(502, "Could not read live RouterOS status. Check API-SSL access, certificate trust and router permissions.")
    finally:
        if pool:
            try:
                pool.disconnect()
            except Exception:
                pass


@app.post("/api/routers/{router_id}/configure-radius")
def configure_router_radius(router_id: str, request: Request, user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        router = conn.execute("SELECT * FROM routers WHERE id=? AND tenant_id=?", (router_id, tid)).fetchone()
        saved = conn.execute("SELECT secrets_encrypted FROM router_secrets WHERE router_id=? AND tenant_id=?", (router_id, tid)).fetchone()
    if not router or not saved:
        raise HTTPException(404, "Router and saved API credentials are required.")
    config = decrypt_json(saved["secrets_encrypted"])
    if not config.get("radius_server") or not config.get("radius_secret"):
        raise HTTPException(400, "Save the RADIUS server address and a unique shared secret first.")
    pool = None
    try:
        pool, api = router_api_connection(dict(router), config)
        resource = api.get_resource("/radius")
        entries = resource.get()
        existing = next((entry for entry in entries
                         if entry.get("address") == config["radius_server"]
                         and {part.strip() for part in str(entry.get("service", "")).split(",")} >= {"hotspot", "ppp"}), None)
        if existing:
            resource.set(id=existing.get(".id") or existing.get("id"), secret=config["radius_secret"], authentication_port="1812", accounting_port="1813")
        else:
            resource.add(service="hotspot,ppp", address=config["radius_server"], secret=config["radius_secret"], authentication_port="1812", accounting_port="1813")

        # Turn on RADIUS for configured Hotspot profiles and PPP AAA. These are
        # explicit changes initiated by the ISP administrator from this action.
        hotspot_profiles = api.get_resource("/ip/hotspot/profile")
        for profile in hotspot_profiles.get():
            hotspot_profiles.set(id=profile[".id"], use_radius="yes")
        ppp_aaa = api.get_resource("/ppp/aaa")
        ppp_aaa_rows = ppp_aaa.get()
        if ppp_aaa_rows and (ppp_aaa_rows[0].get(".id") or ppp_aaa_rows[0].get("id")):
            ppp_aaa.set(id=ppp_aaa_rows[0].get(".id") or ppp_aaa_rows[0].get("id"), use_radius="yes", accounting="yes", interim_update="5m")
        else:
            ppp_aaa.set(use_radius="yes", accounting="yes", interim_update="5m")
        try:
            incoming = api.get_resource("/radius/incoming")
            incoming_rows = incoming.get()
            if incoming_rows and (incoming_rows[0].get(".id") or incoming_rows[0].get("id")):
                incoming.set(id=incoming_rows[0].get(".id") or incoming_rows[0].get("id"), accept="yes", port="1700")
            else:
                incoming.set(accept="yes", port="1700")
        except Exception:
            logger.warning("Router %s did not accept RADIUS incoming/CoA configuration; authentication/accounting setup continued.", router_id)

        if DATABASE_URL and os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() == "true":
            with db_conn() as conn:
                nasname = str(router["host"]).strip()
                conn.execute("SAVEPOINT radius_nas")
                try:
                    conn.execute("DELETE FROM nas WHERE nasname=?", (nasname,))
                    conn.execute("INSERT INTO nas(nasname,shortname,type,secret,description) VALUES(?,?,'other',?,?)",
                                 (nasname, slugify(str(router["name"]))[:32] or "ris-router", config["radius_secret"], f"RIS tenant {tid}"))
                    conn.execute("RELEASE SAVEPOINT radius_nas")
                except Exception:
                    conn.execute("ROLLBACK TO SAVEPOINT radius_nas")
                    conn.execute("RELEASE SAVEPOINT radius_nas")
                    raise
                conn.execute("UPDATE routers SET status='online',last_seen=? WHERE id=? AND tenant_id=?", (now_iso(), router_id, tid))
                audit(conn, user, "router_radius_target_configured", "router", router_id, {"radius_server": config["radius_server"]})
        else:
            with db_conn() as conn:
                conn.execute("UPDATE routers SET status='online',last_seen=? WHERE id=? AND tenant_id=?", (now_iso(), router_id, tid))
                audit(conn, user, "router_radius_target_configured", "router", router_id, {"radius_server": config["radius_server"]})
        return {"success": True, "message": "RADIUS target configured. Hotspot profiles and PPP AAA now use RADIUS with accounting; verify with a dedicated test subscriber before production use."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("RADIUS router configuration failed: %s", exc)
        raise HTTPException(502, "Could not configure the RADIUS target. Check API permissions and RouterOS compatibility.")
    finally:
        if pool:
            try: pool.disconnect()
            except Exception: pass


@app.get("/api/agents")
def list_agents(user: dict = Depends(need_roles("owner", "admin", "finance", "agent"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM agents WHERE tenant_id=? ORDER BY created_at DESC", (tid,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.post("/api/agents")
def add_agent(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    name = str(data.get("name", "")).strip()
    try:
        commission = float(data.get("commission_rate", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "Commission must be numeric.")
    if len(name) < 2 or not 0 <= commission <= 100:
        raise HTTPException(400, "Enter an agent name and commission between 0 and 100%.")
    aid = new_id("AGT")
    with db_conn() as conn:
        require_plan_feature(conn, tid, "agents")
        conn.execute("INSERT INTO agents(id,tenant_id,name,phone,commission_rate,status,created_at) VALUES(?,?,?,?,?,'active',?)", (aid, tid, name, normalize_phone(data.get("phone")), commission, now_iso()))
        audit(conn, user, "agent_created", "agent", aid)
    return {"success": True, "id": aid}


# ---------------------------------------------------------------------------
# Invoices and payments
# ---------------------------------------------------------------------------
@app.get("/api/invoices")
def list_invoices(user: dict = Depends(need_roles("owner", "admin", "finance", "support"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT i.*,c.name customer_name FROM invoices i JOIN customers c ON c.id=i.customer_id AND c.tenant_id=i.tenant_id WHERE i.tenant_id=? ORDER BY i.created_at DESC LIMIT 500", (tid,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


@app.post("/api/invoices")
def add_invoice(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin", "finance"))):
    csrf_check(request)
    tid = tenant_user(user)
    cid = str(data.get("customer_id", ""))
    try:
        amount = int(round(float(data.get("amount", 0))))
    except (TypeError, ValueError):
        raise HTTPException(400, "Invoice amount must be numeric.")
    if amount <= 0:
        raise HTTPException(400, "Invoice amount must be greater than zero.")
    iid = new_id("INV")
    with db_conn() as conn:
        if not conn.execute("SELECT 1 FROM customers WHERE id=? AND tenant_id=?", (cid, tid)).fetchone():
            raise HTTPException(404, "Customer not found in this workspace.")
        conn.execute("INSERT INTO invoices(id,tenant_id,customer_id,amount_minor,currency,status,due_at,created_at) VALUES(?,?,?,?,'UGX','unpaid',?,?)", (iid, tid, cid, amount, data.get("due_at"), now_iso()))
        audit(conn, user, "invoice_created", "invoice", iid)
    return {"success": True, "id": iid}


@app.get("/api/payments")
def list_payments(user: dict = Depends(need_roles("owner", "admin", "finance", "support"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT p.*,c.name customer_name FROM payments p JOIN customers c ON c.id=p.customer_id AND c.tenant_id=p.tenant_id WHERE p.tenant_id=? ORDER BY p.created_at DESC LIMIT 500", (tid,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


def sync_radius_account(conn, tenant_id: str, username: str, password: str, package) -> str:
    if os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() != "true":
        return "not_configured"
    if not DATABASE_URL:
        return "requires_postgresql"
    # A savepoint prevents a RADIUS schema/configuration error from corrupting the
    # transaction that records a verified payment and subscription.
    conn.execute("SAVEPOINT radius_sync")
    try:
        conn.execute("DELETE FROM radcheck WHERE username=?", (username,))
        conn.execute("DELETE FROM radreply WHERE username=?", (username,))
        conn.execute("INSERT INTO radcheck(username,attribute,op,value) VALUES(?, 'Cleartext-Password', ':=', ?)", (username, password))
        rate = ""
        if int(package["speed_down_kbps"] or 0) or int(package["speed_up_kbps"] or 0):
            down = max(1, int(package["speed_down_kbps"] or package["speed_up_kbps"] or 0))
            up = max(1, int(package["speed_up_kbps"] or package["speed_down_kbps"] or 0))
            rate = f"{up}k/{down}k"
            conn.execute("INSERT INTO radreply(username,attribute,op,value) VALUES(?, 'Mikrotik-Rate-Limit', ':=', ?)", (username, rate))
        conn.execute("INSERT INTO radreply(username,attribute,op,value) VALUES(?, 'Session-Timeout', ':=', ?)", (username, str(int(package["validity_hours"]) * 3600)))
        if int(package["data_limit_mb"] or 0) > 0:
            # RouterOS supports independent received/transmitted byte limits in
            # Access-Accept. Split the configured cap evenly: it is conservative
            # (combined usage cannot exceed the package cap), although asymmetric
            # traffic can leave some quota unused. Exact aggregate quota enforcement
            # needs live radacct aggregation and CoA/disconnect handling.
            directional_bytes = max(1, int(package["data_limit_mb"]) * 1024 * 1024 // 2)
            for attribute in ("Mikrotik-Recv-Limit", "Mikrotik-Xmit-Limit"):
                conn.execute("INSERT INTO radreply(username,attribute,op,value) VALUES(?, ?, ':=', ?)", (username, attribute, str(directional_bytes)))
        if int(package["device_limit"] or 0) > 0:
            device_limit = str(int(package["device_limit"]))
            conn.execute("INSERT INTO radcheck(username,attribute,op,value) VALUES(?, 'Simultaneous-Use', ':=', ?)", (username, device_limit))
            conn.execute("INSERT INTO radreply(username,attribute,op,value) VALUES(?, 'Port-Limit', ':=', ?)", (username, device_limit))
        conn.execute("RELEASE SAVEPOINT radius_sync")
        return "provisioned"
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT radius_sync")
        conn.execute("RELEASE SAVEPOINT radius_sync")
        logger.exception("FreeRADIUS SQL provisioning failed for %s", username)
        return "failed"


def ensure_network_account(conn, tenant_id: str, customer_id: str, service_type: str, package) -> dict:
    row = conn.execute("SELECT * FROM network_accounts WHERE customer_id=? AND service_type=?", (customer_id, service_type)).fetchone()
    if row:
        credentials = decrypt_json(row["password_encrypted"])
        username, password = row["username"], credentials["password"]
        conn.execute("UPDATE network_accounts SET status='active',updated_at=? WHERE id=?", (now_iso(), row["id"]))
        account_id = row["id"]
    else:
        tenant = conn.execute("SELECT slug FROM tenants WHERE id=?", (tenant_id,)).fetchone()
        username = f"{tenant['slug'][:12]}_{customer_id[-8:].lower()}"
        password = secrets.token_urlsafe(12)[:16]
        account_id = new_id("NET")
        conn.execute("INSERT INTO network_accounts(id,tenant_id,customer_id,username,password_encrypted,service_type,status,provision_status,created_at,updated_at) VALUES(?,?,?,?,?,?,'active','pending',?,?)",
                     (account_id, tenant_id, customer_id, username, encrypt_json({"password": password}), service_type, now_iso(), now_iso()))
    provision_status = sync_radius_account(conn, tenant_id, username, password, package)
    conn.execute("UPDATE network_accounts SET provision_status=?,updated_at=? WHERE id=?", (provision_status, now_iso(), account_id))
    return {"id": account_id, "username": username, "provision_status": provision_status}


def set_customer_network_state(conn, tenant_id: str, customer_id: str, status: str) -> None:
    """Synchronize local network-account state and RADIUS SQL authorization rows.

    Removing RADIUS authorization prevents new authentications. Existing live
    sessions require CoA/Disconnect support, which is not yet implemented here.
    """
    accounts = conn.execute("SELECT * FROM network_accounts WHERE customer_id=? AND tenant_id=?", (customer_id, tenant_id)).fetchall()
    for account in accounts:
        if status in ("suspended", "archived"):
            conn.execute("UPDATE network_accounts SET status='suspended',provision_status=CASE WHEN provision_status IN ('provisioned','suspended') THEN 'suspended' ELSE provision_status END,updated_at=? WHERE id=?", (now_iso(), account["id"]))
            if DATABASE_URL and os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() == "true":
                conn.execute("DELETE FROM radcheck WHERE username=?", (account["username"],))
                conn.execute("DELETE FROM radreply WHERE username=?", (account["username"],))
        elif status == "active":
            customer = conn.execute("SELECT package_id FROM customers WHERE id=? AND tenant_id=?", (customer_id, tenant_id)).fetchone()
            package = conn.execute("SELECT * FROM packages WHERE id=? AND tenant_id=? AND active=1", (customer["package_id"], tenant_id)).fetchone() if customer and customer["package_id"] else None
            if package and DATABASE_URL and os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() == "true":
                try:
                    password = decrypt_json(account["password_encrypted"])["password"]
                    provision_status = sync_radius_account(conn, tenant_id, account["username"], password, package)
                except Exception:
                    logger.exception("Could not reactivate RADIUS account %s", account["username"])
                    provision_status = "failed"
            else:
                provision_status = account["provision_status"]
            conn.execute("UPDATE network_accounts SET status='active',provision_status=?,updated_at=? WHERE id=?", (provision_status, now_iso(), account["id"]))


def activate_subscription(conn: sqlite3.Connection, tenant_id: str, customer_id: str, package_id: str, payment_id: str) -> str:
    package = conn.execute("SELECT * FROM packages WHERE id=? AND tenant_id=? AND active=1", (package_id, tenant_id)).fetchone()
    if not package:
        raise HTTPException(404, "Package is no longer available.")
    starts = datetime.now(timezone.utc)
    expires = starts + timedelta(hours=int(package["validity_hours"]))
    sub_id = new_id("SUB")
    conn.execute("INSERT INTO subscriptions(id,tenant_id,customer_id,package_id,status,starts_at,expires_at,data_limit_mb,data_used_mb,payment_id,created_at) VALUES(?,?,?,?,'active',?,?,?,0,?,?)",
                 (sub_id, tenant_id, customer_id, package_id, starts.isoformat(), expires.isoformat(), package["data_limit_mb"], payment_id, starts.isoformat()))
    conn.execute("UPDATE customers SET package_id=? WHERE id=? AND tenant_id=?", (package_id, customer_id, tenant_id))
    ensure_network_account(conn, tenant_id, customer_id, str(package["service_type"]), package)
    return sub_id


@app.get("/api/tenant/captive-portal")
def tenant_captive_portal(user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        tenant = conn.execute("SELECT name,slug,brand_name,brand_primary,status FROM tenants WHERE id=?", (tid,)).fetchone()
        row = conn.execute("SELECT * FROM captive_portals WHERE tenant_id=?", (tid,)).fetchone()
        if not row:
            config = {"headline": f"Welcome to {tenant['brand_name'] or tenant['name']}", "welcome_message": "Choose an internet package or enter your voucher to get connected.", "primary_color": tenant["brand_primary"] or "#087bd1", "background_color": "#071a2e", "footer_text": "Powered by RIS", "show_registration": True, "show_packages": True, "show_voucher": True}
            conn.execute("INSERT INTO captive_portals(id,tenant_id,enabled,config_json,created_at,updated_at) VALUES(?,?,1,?,?,?)", (new_id("CPT"), tid, json.dumps(config), now_iso(), now_iso()))
            enabled = True
        else:
            config = json.loads(row["config_json"] or "{}")
            enabled = bool(row["enabled"])
    return {"success": True, "enabled": enabled, "config": config, "portal_url": f"/portal/{tenant['slug']}", "tenant": {"name": tenant["name"], "brand_name": tenant["brand_name"] or tenant["name"], "slug": tenant["slug"], "status": tenant["status"]}}


@app.put("/api/tenant/captive-portal")
def update_tenant_captive_portal(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    allowed = {"headline", "welcome_message", "primary_color", "background_color", "footer_text", "show_registration", "show_packages", "show_voucher"}
    supplied = data.get("config") if isinstance(data.get("config"), dict) else {}
    config = {k: supplied[k] for k in allowed if k in supplied}
    for key in ("headline", "welcome_message", "footer_text"):
        if key in config:
            config[key] = str(config[key]).strip()[:180 if key == "headline" else 500]
    for key in ("primary_color", "background_color"):
        if key in config and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(config[key])):
            raise HTTPException(400, f"{key} must be a six-digit hex colour.")
    for key in ("show_registration", "show_packages", "show_voucher"):
        if key in config:
            config[key] = bool(config[key])
    with db_conn() as conn:
        existing = conn.execute("SELECT config_json FROM captive_portals WHERE tenant_id=?", (tid,)).fetchone()
        current = json.loads(existing["config_json"] or "{}") if existing else {}
        current.update(config)
        enabled = 1 if data.get("enabled", True) else 0
        conn.execute("INSERT INTO captive_portals(id,tenant_id,enabled,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(tenant_id) DO UPDATE SET enabled=excluded.enabled,config_json=excluded.config_json,updated_at=excluded.updated_at", (new_id("CPT"), tid, enabled, json.dumps(current), now_iso(), now_iso()))
        audit(conn, user, "captive_portal_updated", "captive_portal", tid, {"enabled": bool(enabled), "fields": sorted(config.keys())})
    return {"success": True, "enabled": bool(enabled), "config": current, "message": "Captive portal settings saved."}


@app.get("/api/public/portal/{tenant_slug}")
def public_captive_portal(tenant_slug: str):
    with db_conn() as conn:
        tenant = conn.execute("SELECT id,name,slug,brand_name,brand_primary,currency,status FROM tenants WHERE slug=? AND status IN ('trial','active')", (tenant_slug,)).fetchone()
        if not tenant:
            raise HTTPException(404, "This ISP portal is unavailable.")
        portal = conn.execute("SELECT enabled,config_json FROM captive_portals WHERE tenant_id=?", (tenant["id"],)).fetchone()
        if portal and not portal["enabled"]:
            raise HTTPException(404, "This ISP has temporarily disabled its customer portal.")
        config = json.loads(portal["config_json"] or "{}") if portal else {}
        packages = conn.execute("SELECT id,name,service_type,price_minor,currency,validity_hours,data_limit_mb,speed_down_kbps,speed_up_kbps,device_limit FROM packages WHERE tenant_id=? AND active=1 AND service_type='hotspot' ORDER BY price_minor", (tenant["id"],)).fetchall()
    return {"success": True, "tenant": {"name": tenant["name"], "brand_name": tenant["brand_name"] or tenant["name"], "slug": tenant["slug"], "currency": tenant["currency"]}, "config": config, "packages": [dict(x) for x in packages], "trial_mode": ENVIRONMENT != "production" and PAYMENT_MODE == "demo"}


@app.post("/api/public/portal/{tenant_slug}/purchase")
def public_portal_purchase(tenant_slug: str, request: Request, data: dict):
    csrf_check(request)
    if ENVIRONMENT == "production" or PAYMENT_MODE != "demo":
        raise HTTPException(403, "Public demo checkout is disabled. Use the configured live payment checkout.")
    name = str(data.get("name", "")).strip()[:120]
    phone = normalize_phone(data.get("phone", ""))
    package_id = str(data.get("package_id", ""))
    if len(name) < 2:
        raise HTTPException(400, "Enter the customer's name for this trial purchase.")
    if phone and len(re.sub(r"\D", "", phone)) < 9:
        raise HTTPException(400, "Enter a valid phone number or leave it blank.")
    with db_conn() as conn:
        tenant = conn.execute("SELECT id,name FROM tenants WHERE slug=? AND status IN ('trial','active')", (tenant_slug,)).fetchone()
        if not tenant:
            raise HTTPException(404, "ISP portal not found.")
        package = conn.execute("SELECT * FROM packages WHERE id=? AND tenant_id=? AND active=1 AND service_type='hotspot'", (package_id, tenant["id"])).fetchone()
        if not package:
            raise HTTPException(404, "This internet package is unavailable.")
        customer_id, invoice_id, payment_id = new_id("CUS"), new_id("INV"), new_id("PAY")
        reference = "TRIAL-" + uuid.uuid4().hex[:12].upper()
        stamp = now_iso()
        conn.execute("INSERT INTO customers(id,tenant_id,name,email,phone,status,service_type,package_id,created_at) VALUES(?,?,?,'',?,'active','hotspot',?,?)", (customer_id, tenant["id"], name, phone, package["id"], stamp))
        conn.execute("INSERT INTO invoices(id,tenant_id,customer_id,package_id,amount_minor,currency,status,created_at) VALUES(?,?,?,?,?,?,'unpaid',?)", (invoice_id, tenant["id"], customer_id, package["id"], package["price_minor"], package["currency"], stamp))
        conn.execute("INSERT INTO payments(id,tenant_id,customer_id,invoice_id,amount_minor,currency,provider,reference,status,created_at) VALUES(?,?,?,?,?,?, 'trial_demo',?,'pending',?)", (payment_id, tenant["id"], customer_id, invoice_id, package["price_minor"], package["currency"], reference, stamp))
        demo_token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO portal_demo_orders(payment_id,tenant_id,token_hash,expires_at,created_at) VALUES(?,?,?,?,?)", (payment_id, tenant["id"], hashlib.sha256(demo_token.encode()).hexdigest(), (datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(), stamp))
        audit(conn, None, "trial_portal_purchase_started", "payment", payment_id, {"tenant_id": tenant["id"], "package_id": package_id})
    return {"success": True, "payment_id": payment_id, "demo_token": demo_token, "reference": reference, "amount": package["price_minor"], "currency": package["currency"], "message": "Trial checkout created. No money has been requested or collected."}


@app.post("/api/public/portal/{tenant_slug}/purchase/{payment_id}/confirm")
def public_portal_demo_confirm(tenant_slug: str, payment_id: str, request: Request, data: dict):
    csrf_check(request)
    if ENVIRONMENT == "production" or PAYMENT_MODE != "demo":
        raise HTTPException(403, "Trial payment simulation is disabled.")
    token = str(data.get("demo_token", ""))
    if len(token) < 32:
        raise HTTPException(400, "Invalid trial confirmation token.")
    with db_conn() as conn:
        row = conn.execute("SELECT p.*,o.token_hash,o.expires_at,o.redeemed_at,t.slug FROM payments p JOIN portal_demo_orders o ON o.payment_id=p.id JOIN tenants t ON t.id=p.tenant_id WHERE p.id=? AND t.slug=?", (payment_id, tenant_slug)).fetchone()
        if not row or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), row["token_hash"]):
            raise HTTPException(404, "Trial checkout not found or token is invalid.")
        if row["redeemed_at"]:
            return {"success": True, "status": "paid", "message": "This trial checkout was already completed."}
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(410, "This trial checkout expired. Start again.")
        conn.execute("UPDATE payments SET status='paid',paid_at=? WHERE id=? AND status='pending'", (now_iso(), payment_id))
        conn.execute("UPDATE invoices SET status='paid' WHERE id=?", (row["invoice_id"],))
        invoice = conn.execute("SELECT customer_id,package_id FROM invoices WHERE id=? AND tenant_id=?", (row["invoice_id"], row["tenant_id"])).fetchone()
        package = conn.execute("SELECT * FROM packages WHERE id=? AND tenant_id=?", (invoice["package_id"], row["tenant_id"])).fetchone()
        starts = datetime.now(timezone.utc); expires = starts + timedelta(hours=int(package["validity_hours"]))
        sub_id = new_id("SUB")
        conn.execute("INSERT INTO subscriptions(id,tenant_id,customer_id,package_id,status,starts_at,expires_at,data_limit_mb,data_used_mb,payment_id,created_at) VALUES(?,?,?,?,'active',?,?,?,0,?,?)", (sub_id,row["tenant_id"],invoice["customer_id"],package["id"],starts.isoformat(),expires.isoformat(),package["data_limit_mb"],payment_id,starts.isoformat()))
        conn.execute("UPDATE customers SET package_id=? WHERE id=? AND tenant_id=?", (package["id"], invoice["customer_id"], row["tenant_id"]))
        # Trial mode deliberately does not create RADIUS credentials or touch a router.
        session_id = new_id("PSN")
        conn.execute("INSERT INTO portal_sessions(id,tenant_id,customer_id,subscription_id,source,status,started_at,expires_at) VALUES(?,?,?,?,'trial_simulation','active',?,?)", (session_id,row["tenant_id"],invoice["customer_id"],sub_id,starts.isoformat(),expires.isoformat()))
        conn.execute("UPDATE portal_demo_orders SET redeemed_at=? WHERE payment_id=?", (now_iso(), payment_id))
        audit(conn, None, "trial_portal_purchase_confirmed", "subscription", sub_id, {"tenant_id": row["tenant_id"], "payment_id": payment_id})
    return {"success": True, "status": "paid", "subscription_id": sub_id, "session_id": session_id, "expires_at": expires.isoformat(), "message": "TRIAL SIMULATION: package activated in the RIS test database. No real payment was made and no router or RADIUS server was changed."}


@app.post("/api/public/portal/{tenant_slug}/redeem-voucher")
def public_portal_redeem_voucher(tenant_slug: str, request: Request, data: dict):
    csrf_check(request)
    if ENVIRONMENT == "production" or PAYMENT_MODE != "demo":
        raise HTTPException(403, "Live voucher authentication is not enabled until router/RADIUS provisioning is configured and verified.")
    code = re.sub(r"[^A-Za-z0-9-]", "", str(data.get("code", "")).strip()).upper()
    name = str(data.get("name", "Trial customer")).strip()[:120] or "Trial customer"
    if not code:
        raise HTTPException(400, "Enter a voucher code.")
    with db_conn() as conn:
        tenant = conn.execute("SELECT id FROM tenants WHERE slug=? AND status IN ('trial','active')", (tenant_slug,)).fetchone()
        if not tenant:
            raise HTTPException(404, "ISP portal not found.")
        voucher = conn.execute("SELECT v.*,p.name AS package_name,p.validity_hours,p.data_limit_mb,p.price_minor,p.currency,p.service_type FROM vouchers v JOIN packages p ON p.id=v.package_id AND p.tenant_id=v.tenant_id WHERE v.code=? AND v.tenant_id=? AND v.status='unused' AND p.active=1", (code, tenant["id"])).fetchone()
        if not voucher:
            raise HTTPException(400, "Voucher is invalid, already used or unavailable.")
        if voucher["expires_at"] and datetime.fromisoformat(voucher["expires_at"]) < datetime.now(timezone.utc):
            conn.execute("UPDATE vouchers SET status='expired' WHERE code=? AND tenant_id=?", (code, tenant["id"]))
            raise HTTPException(410, "This voucher has expired.")
        customer_id = new_id("CUS"); stamp=now_iso(); sub_id=new_id("SUB")
        conn.execute("INSERT INTO customers(id,tenant_id,name,email,phone,status,service_type,package_id,created_at) VALUES(?,?,?,'','','active',?,?,?)", (customer_id,tenant["id"],name,voucher["service_type"],voucher["package_id"],stamp))
        starts=datetime.now(timezone.utc); expires=starts+timedelta(hours=int(voucher["validity_hours"]))
        conn.execute("INSERT INTO subscriptions(id,tenant_id,customer_id,package_id,status,starts_at,expires_at,data_limit_mb,data_used_mb,created_at) VALUES(?,?,?,?,'active',?,?,?,0,?)", (sub_id,tenant["id"],customer_id,voucher["package_id"],starts.isoformat(),expires.isoformat(),voucher["data_limit_mb"],stamp))
        conn.execute("UPDATE vouchers SET status='used',redeemed_by=? WHERE code=? AND tenant_id=? AND status='unused'", (customer_id,code,tenant["id"]))
        conn.execute("UPDATE customers SET package_id=? WHERE id=? AND tenant_id=?", (voucher["package_id"],customer_id,tenant["id"]))
        session_id=new_id("PSN")
        conn.execute("INSERT INTO portal_sessions(id,tenant_id,customer_id,subscription_id,source,status,started_at,expires_at) VALUES(?,?,?,?,'voucher_trial','active',?,?)", (session_id,tenant["id"],customer_id,sub_id,starts.isoformat(),expires.isoformat()))
        audit(conn,None,"trial_voucher_redeemed","voucher",code,{"tenant_id":tenant["id"],"customer_id":customer_id})
    return {"success":True,"status":"active","package":voucher["package_name"],"expires_at":expires.isoformat(),"session_id":session_id,"message":"TRIAL VOUCHER ACCEPTED: the test subscription is active. No router was configured or changed."}


@app.post("/api/portal/purchase")
def portal_purchase(request: Request, data: dict, user: dict = Depends(need_roles("customer"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
        package = conn.execute("SELECT * FROM packages WHERE id=? AND tenant_id=? AND active=1", (str(data.get("package_id", "")), tid)).fetchone()
        if not customer or not package:
            raise HTTPException(404, "Customer or active package not found.")
        invoice_id, payment_id, reference = new_id("INV"), new_id("PAY"), "RIS-" + uuid.uuid4().hex[:16].upper()
        conn.execute("INSERT INTO invoices(id,tenant_id,customer_id,package_id,amount_minor,currency,status,created_at) VALUES(?,?,?,?,?,'UGX','unpaid',?)", (invoice_id, tid, customer["id"], package["id"], package["price_minor"], now_iso()))
        conn.execute("INSERT INTO payments(id,tenant_id,customer_id,invoice_id,amount_minor,currency,provider,reference,status,created_at) VALUES(?,?,?,?,?,'UGX',? ,?,'pending',?)", (payment_id, tid, customer["id"], invoice_id, package["price_minor"], "development" if PAYMENT_MODE == "demo" else "manual", reference, now_iso()))
        audit(conn, user, "package_purchase_started", "payment", payment_id, {"package_id": package["id"]})
    return {"success": True, "invoice_id": invoice_id, "payment_id": payment_id, "reference": reference, "amount": package["price_minor"], "currency": "UGX", "status": "pending", "payment_mode": PAYMENT_MODE, "message": "Payment record created. Confirm it using the development payment button or configure a live provider."}


@app.post("/api/payments/{payment_id}/demo-confirm")
def demo_confirm_payment(payment_id: str, request: Request, user: dict = Depends(current_user)):
    csrf_check(request)
    if ENVIRONMENT == "production" or PAYMENT_MODE != "demo":
        raise HTTPException(403, "Development payment simulation is disabled.")
    tid = tenant_user(user)
    with db_conn() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id=? AND tenant_id=?", (payment_id, tid)).fetchone()
        if not payment:
            raise HTTPException(404, "Payment not found.")
        if payment["status"] == "paid":
            return {"success": True, "message": "Payment was already confirmed.", "status": "paid"}
        if user["role"] == "customer":
            customer = conn.execute("SELECT id FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
            if not customer or customer["id"] != payment["customer_id"]:
                raise HTTPException(403, "You can only confirm your own development payment.")
        conn.execute("UPDATE payments SET status='paid',paid_at=? WHERE id=?", (now_iso(), payment_id))
        conn.execute("UPDATE invoices SET status='paid' WHERE id=?", (payment["invoice_id"],))
        invoice = conn.execute("SELECT package_id FROM invoices WHERE id=?", (payment["invoice_id"],)).fetchone()
        subscription_id = None
        if invoice and invoice["package_id"]:
            subscription_id = activate_subscription(conn, tid, payment["customer_id"], invoice["package_id"], payment_id)
        audit(conn, user, "development_payment_confirmed", "payment", payment_id, {"subscription_id": subscription_id})
    return {"success": True, "status": "paid", "subscription_id": subscription_id, "message": "DEVELOPMENT SIMULATION ONLY: service record activated in the RIS database. No real money was collected and no router was changed."}


# ---------------------------------------------------------------------------
# RIS SaaS billing: the ISP pays RIS for its own workspace subscription.
# This ledger is separate from the ISP's end-customer payments.
# ---------------------------------------------------------------------------
def platform_invoice_paid(conn, invoice_id: str, provider: str, transaction_id: str = "") -> None:
    invoice = conn.execute("SELECT * FROM platform_invoices WHERE id=?", (invoice_id,)).fetchone()
    if not invoice:
        raise HTTPException(404, "RIS subscription invoice not found.")
    if invoice["status"] == "paid":
        return
    conn.execute("UPDATE platform_invoices SET status='paid',paid_at=? WHERE id=?", (now_iso(), invoice_id))
    conn.execute("UPDATE tenant_subscriptions SET plan_code=COALESCE(?,plan_code),billing_cycle=?,status='active',period_start=?,period_end=?,trial_ends_at=NULL,grace_ends_at=NULL,next_invoice_at=?,updated_at=? WHERE tenant_id=?",
                 (invoice["plan_code"], invoice["billing_cycle"], invoice["period_start"], invoice["period_end"], invoice["period_end"], now_iso(), invoice["tenant_id"]))
    conn.execute("UPDATE tenants SET status='active',plan=? WHERE id=?", (invoice["plan_code"], invoice["tenant_id"]))
    conn.execute("UPDATE platform_payments SET status='paid',paid_at=? WHERE invoice_id=?", (now_iso(), invoice_id))


@app.get("/api/tenant/billing")
def tenant_billing(user: dict = Depends(need_roles("owner", "admin", "finance"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        sub = conn.execute("SELECT s.*,p.name plan_name,p.monthly_price,p.annual_price,p.currency,p.max_customers,p.max_routers,p.features_json FROM tenant_subscriptions s JOIN saas_plans p ON p.code=s.plan_code WHERE s.tenant_id=?", (tid,)).fetchone()
        invoices = conn.execute("SELECT * FROM platform_invoices WHERE tenant_id=? ORDER BY created_at DESC LIMIT 30", (tid,)).fetchall()
        plans = conn.execute("SELECT code,name,monthly_price,annual_price,currency,max_customers,max_routers,features_json FROM saas_plans WHERE active=1 ORDER BY monthly_price").fetchall()
    return {"success": True, "subscription": dict(sub) if sub else None, "invoices": [dict(x) for x in invoices], "plans": [dict(x) for x in plans], "payment_mode": PAYMENT_MODE, "environment": ENVIRONMENT}


@app.get("/api/tenant/usage")
def tenant_usage(user: dict = Depends(need_roles("owner", "admin", "finance", "network_admin"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        plan = tenant_plan(conn, tid)
        counts = {
            "customers": conn.execute("SELECT COUNT(*) n FROM customers WHERE tenant_id=?", (tid,)).fetchone()["n"],
            "routers": conn.execute("SELECT COUNT(*) n FROM routers WHERE tenant_id=?", (tid,)).fetchone()["n"],
            "agents": conn.execute("SELECT COUNT(*) n FROM agents WHERE tenant_id=?", (tid,)).fetchone()["n"],
        }
    return {"success": True, "plan": {"code": plan.get("code"), "name": plan.get("name")}, "usage": counts,
            "limits": {"customers": plan.get("max_customers"), "routers": plan.get("max_routers")},
            "features": json.loads(plan.get("features_json") or "{}")}


@app.post("/api/tenant/billing/choose-plan")
def tenant_choose_plan(request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    code = str(data.get("plan_code", "starter")).lower()
    cycle = str(data.get("billing_cycle", "monthly")).lower()
    if cycle not in ("monthly", "annual"):
        raise HTTPException(400, "Billing cycle must be monthly or annual.")
    with db_conn() as conn:
        plan = conn.execute("SELECT * FROM saas_plans WHERE code=? AND active=1", (code,)).fetchone()
        sub = conn.execute("SELECT * FROM tenant_subscriptions WHERE tenant_id=?", (tid,)).fetchone()
        if not plan or not sub:
            raise HTTPException(404, "Subscription plan or workspace subscription was not found.")
        amount = int(plan["monthly_price"] if cycle == "monthly" else plan["annual_price"])
        start = now_iso()
        end = (datetime.now(timezone.utc) + (timedelta(days=365) if cycle == "annual" else timedelta(days=30))).isoformat()
        invoice_id = new_id("RINV")
        conn.execute("INSERT INTO platform_invoices(id,tenant_id,subscription_id,period_start,period_end,amount,currency,plan_code,billing_cycle,status,due_at,created_at) VALUES(?,?,?,?,?,?,'UGX',?,?,'unpaid',?,?)",
                     (invoice_id, tid, sub["id"], start, end, amount, code, cycle, (datetime.now(timezone.utc)+timedelta(days=7)).isoformat(), now_iso()))
        if amount == 0:
            platform_invoice_paid(conn, invoice_id, "zero-cost-plan")
        audit(conn, user, "saas_plan_invoice_created", "platform_invoice", invoice_id, {"plan": code, "cycle": cycle})
    return {"success": True, "invoice_id": invoice_id, "amount": amount, "currency": "UGX", "message": "RIS subscription invoice created. Pay it to activate the selected plan."}


@app.post("/api/tenant/billing/invoices/{invoice_id}/checkout")
def tenant_billing_checkout(invoice_id: str, request: Request, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    secret = os.getenv("RIS_PLATFORM_FLW_SECRET_KEY", "").strip()
    if not secret:
        raise HTTPException(400, "RIS platform Flutterwave credentials are not configured. Contact RIS platform support.")
    with db_conn() as conn:
        invoice = conn.execute("SELECT i.*,t.email,t.name FROM platform_invoices i JOIN tenants t ON t.id=i.tenant_id WHERE i.id=? AND i.tenant_id=?", (invoice_id, tid)).fetchone()
        existing = conn.execute("SELECT * FROM platform_payments WHERE invoice_id=? AND status IN ('creating','pending') ORDER BY created_at DESC LIMIT 1", (invoice_id,)).fetchone()
    if not invoice or invoice["status"] == "paid":
        raise HTTPException(404, "Unpaid RIS subscription invoice not found.")
    if existing:
        if existing["checkout_url"]:
            return {"success": True, "checkout_url": existing["checkout_url"], "reference": existing["reference"],
                    "message": "An existing RIS subscription checkout is still open. Reusing it to avoid duplicate charging."}
        raise HTTPException(409, "A checkout for this RIS invoice is already being created. Refresh the invoice before retrying.")
    tx_ref = "RIS-SAAS-" + invoice_id + "-" + uuid.uuid4().hex[:8]
    platform_payment_id = new_id("SPAY")
    try:
        with db_conn() as conn:
            conn.execute("INSERT INTO platform_payments(id,invoice_id,provider,reference,amount,currency,status,checkout_url,created_at) VALUES(?,?,?,?,?,?,'creating',NULL,?)",
                         (platform_payment_id, invoice_id, "flutterwave", tx_ref, invoice["amount"], invoice["currency"], now_iso()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A RIS subscription checkout is already open for this invoice.")
    base = public_base_url(request)
    body = {"tx_ref": tx_ref, "amount": invoice["amount"], "currency": invoice["currency"], "redirect_url": base + "/payments/return",
            "customer": {"email": invoice["email"], "name": invoice["name"]},
            "meta": {"ris_platform_invoice": invoice_id, "ris_tenant_id": tid},
            "customizations": {"title": "RIS SaaS subscription", "description": f"{invoice['plan_code']} plan"}}
    try:
        response = requests.post("https://api.flutterwave.com/v3/payments", json=body,
                                 headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}, timeout=25)
        response.raise_for_status()
        link = response.json().get("data", {}).get("link")
        if not link:
            raise HTTPException(502, "Flutterwave did not return a checkout link.")
    except Exception as exc:
        with db_conn() as conn:
            conn.execute("UPDATE platform_payments SET status='failed' WHERE id=? AND status='creating'", (platform_payment_id,))
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, "Could not create RIS subscription checkout. Check platform payment credentials.")
    with db_conn() as conn:
        conn.execute("UPDATE platform_payments SET status='pending',checkout_url=? WHERE id=?", (link, platform_payment_id))
    return {"success": True, "checkout_url": link, "reference": tx_ref}


@app.post("/api/tenant/billing/invoices/{invoice_id}/demo-confirm")
def tenant_billing_demo_confirm(invoice_id: str, request: Request, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    if ENVIRONMENT == "production" or PAYMENT_MODE != "demo":
        raise HTTPException(403, "RIS subscription payment simulation is disabled.")
    tid = tenant_user(user)
    with db_conn() as conn:
        invoice = conn.execute("SELECT * FROM platform_invoices WHERE id=? AND tenant_id=?", (invoice_id, tid)).fetchone()
        if not invoice:
            raise HTTPException(404, "Invoice not found.")
        platform_invoice_paid(conn, invoice_id, "development")
        conn.execute("INSERT INTO platform_payments(id,invoice_id,provider,reference,amount,currency,status,created_at,paid_at) VALUES(?,?,?,?,?,?,'paid',?,?)",
                     (new_id("SPAY"), invoice_id, "development", "DEMO-" + uuid.uuid4().hex[:14], invoice["amount"], invoice["currency"], now_iso(), now_iso()))
        audit(conn, user, "ris_subscription_demo_paid", "platform_invoice", invoice_id)
    return {"success": True, "message": "DEVELOPMENT SIMULATION ONLY: RIS plan changed in the local database. No real money was collected."}


@app.get("/api/platform/billing")
def platform_billing(user: dict = Depends(need_roles("platform_admin"))):
    with db_conn() as conn:
        invoices = conn.execute("SELECT i.*,t.name tenant_name,t.slug tenant_slug FROM platform_invoices i JOIN tenants t ON t.id=i.tenant_id ORDER BY i.created_at DESC LIMIT 500").fetchall()
        plans = conn.execute("SELECT * FROM saas_plans ORDER BY monthly_price").fetchall()
        stats = conn.execute("SELECT COUNT(*) invoice_count,COALESCE(SUM(CASE WHEN status='paid' THEN amount ELSE 0 END),0) collected,COALESCE(SUM(CASE WHEN status='unpaid' THEN amount ELSE 0 END),0) outstanding FROM platform_invoices").fetchone()
    return {"success": True, "invoices": [dict(x) for x in invoices], "plans": [dict(x) for x in plans], "summary": dict(stats)}


@app.post("/api/webhooks/flutterwave-platform")
async def flutterwave_platform_webhook(request: Request):
    expected = os.getenv("RIS_PLATFORM_FLW_WEBHOOK_SECRET", "").strip()
    signature = request.headers.get("verif-hash", "")
    if not expected or not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Invalid RIS platform payment signature.")
    body = await request.json()
    transaction_id = str((body.get("data") or {}).get("id", ""))
    tx_ref = str((body.get("data") or {}).get("tx_ref", ""))
    secret = os.getenv("RIS_PLATFORM_FLW_SECRET_KEY", "").strip()
    if not transaction_id or not secret:
        return {"success": True, "ignored": True}
    response = requests.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify", headers={"Authorization": f"Bearer {secret}"}, timeout=25)
    response.raise_for_status()
    verified = response.json().get("data") or {}
    with db_conn() as conn:
        platform_payment = conn.execute("SELECT p.*,i.id invoice_id,i.tenant_id FROM platform_payments p JOIN platform_invoices i ON i.id=p.invoice_id WHERE p.reference=?", (tx_ref,)).fetchone()
        if not platform_payment:
            return {"success": True, "ignored": True}
        if verified.get("status") != "successful" or verified.get("tx_ref") != tx_ref or int(float(verified.get("amount", 0))) != int(platform_payment["amount"]) or str(verified.get("currency", "")).upper() != platform_payment["currency"]:
            raise HTTPException(400, "Verified RIS subscription payment does not match the invoice.")
        conn.execute("UPDATE platform_payments SET status='paid',paid_at=? WHERE id=?", (now_iso(), platform_payment["id"]))
        platform_invoice_paid(conn, platform_payment["invoice_id"], "flutterwave", transaction_id)
        conn.execute("UPDATE platform_payments SET status='paid',paid_at=? WHERE id=?", (now_iso(), platform_payment["id"]))
    return {"success": True}


# ---------------------------------------------------------------------------
# Customer self-service portal
# ---------------------------------------------------------------------------
@app.get("/api/portal/packages")
def portal_packages(user: dict = Depends(need_roles("customer"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        rows = conn.execute("SELECT id,name,service_type,price_minor,currency,validity_hours,data_limit_mb,speed_down_kbps,speed_up_kbps,device_limit FROM packages WHERE tenant_id=? AND active=1 ORDER BY price_minor", (tid,)).fetchall()
    with db_conn() as conn:
        integrations = provider_status(conn, tid)
    return {"success": True, "items": [dict(r) for r in rows], "payment_providers": integrations}


@app.get("/api/portal/network-credentials")
def portal_network_credentials(user: dict = Depends(need_roles("customer"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        customer = conn.execute("SELECT id FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
        account = conn.execute("SELECT username,password_encrypted,service_type,status,provision_status FROM network_accounts WHERE customer_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 1", (customer["id"], tid)).fetchone() if customer else None
    if not account:
        return {"success": True, "account": None, "message": "Network login is issued after your first confirmed package purchase."}
    credentials = decrypt_json(account["password_encrypted"])
    return {"success": True, "account": {"username": account["username"], "password": credentials["password"], "service_type": account["service_type"], "status": account["status"], "provision_status": account["provision_status"]}}


@app.get("/api/portal/summary")
def portal_summary(user: dict = Depends(need_roles("customer"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        customer = conn.execute("SELECT * FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
        if not customer:
            raise HTTPException(404, "Customer profile not found.")
        subscriptions = conn.execute("SELECT s.*,p.name package_name FROM subscriptions s JOIN packages p ON p.id=s.package_id AND p.tenant_id=s.tenant_id WHERE s.customer_id=? AND s.tenant_id=? ORDER BY s.created_at DESC", (customer["id"], tid)).fetchall()
        payments = conn.execute("SELECT id,reference,amount_minor,currency,status,created_at,paid_at FROM payments WHERE customer_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 10", (customer["id"], tid)).fetchall()
    return {"success": True, "customer": dict(customer), "subscriptions": [dict(x) for x in subscriptions], "payments": [dict(x) for x in payments]}


# ---------------------------------------------------------------------------
# Tenant-owned provider credentials. Secrets are encrypted before persistence.
# ---------------------------------------------------------------------------
@app.get("/api/tenant/integrations")
def tenant_integrations(user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    tid = tenant_user(user)
    with db_conn() as conn:
        providers = provider_status(conn, tid)
    return {"success": True, "providers": providers}


@app.post("/api/tenant/integrations/{provider}/test")
def tenant_integration_test(provider: str, request: Request, user: dict = Depends(need_roles("owner", "admin", "network_admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    with db_conn() as conn:
        integration = get_tenant_integration(conn, tid, provider)
    if not integration:
        raise HTTPException(404, "Save this provider's credentials first.")
    secrets_data, config = integration
    try:
        if provider == "flutterwave":
            response = requests.get("https://api.flutterwave.com/v3/banks/UG",
                                    headers={"Authorization": f"Bearer {secrets_data['secret_key']}", "Accept": "application/json"}, timeout=20)
            response.raise_for_status()
            return {"success": True, "provider": provider, "status": "reachable", "message": "Flutterwave accepted the API credential and returned the Uganda bank list."}
        if provider == "mtn_momo":
            token, base = mtn_access_token(secrets_data, config)
            return {"success": bool(token), "provider": provider, "status": "authenticated", "environment": config.get("environment"), "message": "MTN MoMo Collection API authentication succeeded."}
        if provider == "airtel_money":
            raise HTTPException(501, "Airtel Money Uganda API adapter is not enabled yet. Credentials are stored encrypted only.")
        raise HTTPException(400, "Unsupported provider.")
    except HTTPException:
        raise
    except requests.RequestException as exc:
        logger.warning("Provider test failed for %s: %s", provider, exc)
        raise HTTPException(502, "Provider authentication test failed. Check the environment, key, API user and subscription key.")


@app.put("/api/tenant/integrations/{provider}")
def tenant_integration_update(provider: str, request: Request, data: dict, user: dict = Depends(need_roles("owner", "admin"))):
    csrf_check(request)
    tid = tenant_user(user)
    secrets_data = data.get("secrets") if isinstance(data.get("secrets"), dict) else {}
    config = data.get("config") if isinstance(data.get("config"), dict) else {}
    with db_conn() as conn:
        save_tenant_integration(conn, tid, provider, secrets_data, config)
        audit(conn, user, "payment_integration_configured", "integration", provider, {"provider": provider})
        statuses = provider_status(conn, tid)
    return {"success": True, "providers": statuses, "message": "Provider credentials encrypted and saved. Run a provider sandbox test before accepting real payments."}


# ---------------------------------------------------------------------------
# Payment gateway adapters and verified callbacks
# ---------------------------------------------------------------------------
def public_base_url(request: Request) -> str:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def verify_flutterwave_transaction(secret_key: str, transaction_id: str, payment: dict) -> dict:
    response = requests.get(f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify",
                            headers={"Authorization": f"Bearer {secret_key}", "Accept": "application/json"}, timeout=25)
    response.raise_for_status()
    body = response.json()
    data = body.get("data") or {}
    expected_amount = int(payment["amount_minor"])
    actual_amount = int(float(data.get("amount", 0))) if data.get("amount") is not None else -1
    if body.get("status") != "success" or data.get("status") != "successful":
        raise HTTPException(400, "Flutterwave has not confirmed a successful payment.")
    if str(data.get("tx_ref", "")) != str(payment["reference"]):
        raise HTTPException(400, "Flutterwave transaction reference does not match this payment.")
    if actual_amount != expected_amount or str(data.get("currency", "")).upper() != str(payment["currency"]).upper():
        raise HTTPException(400, "Flutterwave amount or currency does not match the RIS invoice.")
    return data


def mtn_access_token(secrets_data: dict, config: dict) -> tuple[str, str]:
    base = "https://sandbox.momodeveloper.mtn.com" if config.get("environment") == "sandbox" else "https://momodeveloper.mtn.com"
    response = requests.post(f"{base}/collection/token/", auth=(secrets_data["api_user"], secrets_data["api_key"]),
                             headers={"Ocp-Apim-Subscription-Key": secrets_data["subscription_key"], "Content-Type": "application/json"}, timeout=25)
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(502, "MTN did not return an access token.")
    return token, base


def verify_mtn_payment(secrets_data: dict, config: dict, attempt: dict, payment: dict) -> dict:
    token, base = mtn_access_token(secrets_data, config)
    response = requests.get(f"{base}/collection/v1_0/requesttopay/{attempt['provider_reference']}",
                            headers={"Authorization": f"Bearer {token}", "Ocp-Apim-Subscription-Key": secrets_data["subscription_key"],
                                     "X-Target-Environment": config.get("target_environment", "mtnuganda"), "Accept": "application/json"}, timeout=25)
    response.raise_for_status()
    data = response.json()
    if data.get("status") != "SUCCESSFUL":
        return {"status": str(data.get("status", "PENDING")).lower(), "data": data}
    if str(data.get("externalId", "")) != str(payment["reference"]):
        raise HTTPException(400, "MTN transaction reference does not match this RIS payment.")
    if data.get("amount") is not None and int(float(data["amount"])) != int(payment["amount_minor"]):
        raise HTTPException(400, "MTN payment amount does not match this RIS invoice.")
    if data.get("currency") and str(data["currency"]).upper() != str(payment["currency"]).upper():
        raise HTTPException(400, "MTN payment currency does not match this RIS invoice.")
    return {"status": "successful", "data": data}


@app.post("/api/payments/{payment_id}/checkout")
def payment_checkout(payment_id: str, request: Request, data: dict, user: dict = Depends(current_user)):
    csrf_check(request)
    tid = tenant_user(user)
    provider = str(data.get("provider", "")).lower()
    if provider not in ("flutterwave", "mtn_momo"):
        raise HTTPException(400, "Choose a configured Flutterwave or MTN MoMo integration.")
    with db_conn() as conn:
        payment = conn.execute("SELECT p.*,c.name customer_name,c.email customer_email,c.phone customer_phone,t.slug tenant_slug,t.name tenant_name FROM payments p JOIN customers c ON c.id=p.customer_id AND c.tenant_id=p.tenant_id JOIN tenants t ON t.id=p.tenant_id WHERE p.id=? AND p.tenant_id=?", (payment_id, tid)).fetchone()
        if not payment:
            raise HTTPException(404, "Payment not found.")
        if user["role"] == "customer":
            customer = conn.execute("SELECT id FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
            if not customer or customer["id"] != payment["customer_id"]:
                raise HTTPException(403, "You can only pay your own invoice.")
        if payment["status"] == "paid":
            raise HTTPException(409, "This payment has already been confirmed.")
        pending_attempt = conn.execute("SELECT * FROM payment_attempts WHERE payment_id=? AND tenant_id=? AND status IN ('creating','pending') ORDER BY created_at DESC LIMIT 1", (payment_id, tid)).fetchone()
        integration = get_tenant_integration(conn, tid, provider)
    if pending_attempt:
        if pending_attempt["provider"] != provider:
            raise HTTPException(409, "A payment request is already open with another provider. Verify or resolve it before starting a second charge.")
        return {"success": True, "provider": provider, "checkout_url": pending_attempt["checkout_url"],
                "provider_reference": pending_attempt["provider_reference"],
                "message": "An existing payment request is still open. Continue with that checkout or verify its status; RIS did not create a second charge."}
    if not integration:
        raise HTTPException(400, f"{provider} is not configured for this ISP.")
    secrets_data, config = integration
    base_url = public_base_url(request)
    attempt_id = new_id("ATT")
    provider_ref = payment["reference"] if provider == "flutterwave" else str(uuid.uuid4())
    transaction_id = None if provider == "flutterwave" else provider_ref
    # Reserve one open attempt atomically before contacting a gateway. A unique
    # partial index prevents duplicate clicks/races from creating a second charge.
    try:
        with db_conn() as conn:
            conn.execute("INSERT INTO payment_attempts(id,tenant_id,payment_id,provider,provider_reference,provider_transaction_id,status,checkout_url,response_json,created_at,updated_at) VALUES(?,?,?,?,?,?,'creating',NULL,'{}',?,?)",
                         (attempt_id, tid, payment_id, provider, provider_ref, transaction_id, now_iso(), now_iso()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A payment request is already being created for this payment. Refresh its status before retrying.")
    try:
        if provider == "flutterwave":
            tx_ref = payment["reference"]
            body = {"tx_ref": tx_ref, "amount": payment["amount_minor"], "currency": payment["currency"],
                    "redirect_url": f"{base_url}/payments/return", "customer": {"email": payment["customer_email"],
                    "name": payment["customer_name"], "phonenumber": payment["customer_phone"]},
                    "meta": {"ris_payment_id": payment_id, "ris_tenant_id": tid, "tenant_slug": payment["tenant_slug"]},
                    "customizations": {"title": payment["tenant_name"], "description": "Internet package payment", "logo": base_url + "/assets/ris-logo.png"}}
            response = requests.post("https://api.flutterwave.com/v3/payments", json=body,
                                     headers={"Authorization": f"Bearer {secrets_data['secret_key']}", "Content-Type": "application/json"}, timeout=25)
            response.raise_for_status()
            checkout_url = response.json().get("data", {}).get("link")
            if not checkout_url:
                raise HTTPException(502, "Flutterwave did not return a checkout link.")
            provider_ref = tx_ref
            transaction_id = None
            message = "Secure Flutterwave checkout created. The payment is not active until RIS verifies the provider transaction."
        else:
            token, mtn_base = mtn_access_token(secrets_data, config)
            provider_ref = str(uuid.uuid4())
            callback_url = f"{base_url}/api/webhooks/mtn/{payment['tenant_slug']}?reference_id={provider_ref}"
            body = {"amount": str(payment["amount_minor"]), "currency": payment["currency"], "externalId": payment["reference"],
                    "payer": {"partyIdType": "MSISDN", "partyId": payment["customer_phone"].lstrip("+")},
                    "payerMessage": "RIS internet package", "payeeNote": payment["tenant_name"]}
            response = requests.post(f"{mtn_base}/collection/v1_0/requesttopay", json=body,
                headers={"Authorization": f"Bearer {token}", "X-Reference-Id": provider_ref,
                         "X-Target-Environment": config.get("target_environment", "mtnuganda"),
                         "Ocp-Apim-Subscription-Key": secrets_data["subscription_key"],
                         "X-Callback-Url": callback_url, "Content-Type": "application/json"}, timeout=25)
            if response.status_code not in (200, 202):
                response.raise_for_status()
            checkout_url = None
            transaction_id = provider_ref
            message = "MTN MoMo payment prompt requested. Approve it on your phone; RIS will verify status with MTN before activation."
        with db_conn() as conn:
            conn.execute("UPDATE payment_attempts SET status='pending',checkout_url=?,response_json=?,updated_at=? WHERE id=? AND tenant_id=?",
                         (checkout_url, json.dumps({"http_status": response.status_code}), now_iso(), attempt_id, tid))
            conn.execute("UPDATE payments SET provider=? WHERE id=? AND tenant_id=?", (provider, payment_id, tid))
            audit(conn, user, "payment_checkout_created", "payment", payment_id, {"provider": provider})
        return {"success": True, "provider": provider, "checkout_url": checkout_url, "provider_reference": provider_ref, "message": message}
    except HTTPException:
        with db_conn() as conn:
            conn.execute("UPDATE payment_attempts SET status='failed',updated_at=? WHERE id=? AND tenant_id=? AND status='creating'", (now_iso(), attempt_id, tid))
        raise
    except requests.RequestException as exc:
        with db_conn() as conn:
            conn.execute("UPDATE payment_attempts SET status='failed',response_json=?,updated_at=? WHERE id=? AND tenant_id=? AND status='creating'", (json.dumps({"error": type(exc).__name__}), now_iso(), attempt_id, tid))
        logger.warning("Payment provider checkout failed (%s): %s", provider, exc)
        raise HTTPException(502, f"{provider} could not create a payment request. Check credentials and provider environment.")
    except Exception:
        with db_conn() as conn:
            conn.execute("UPDATE payment_attempts SET status='failed',updated_at=? WHERE id=? AND tenant_id=? AND status='creating'", (now_iso(), attempt_id, tid))
        raise


@app.post("/api/payments/{payment_id}/verify")
def verify_payment(payment_id: str, request: Request, data: dict | None = None, user: dict = Depends(current_user)):
    csrf_check(request)
    tid = tenant_user(user)
    data = data or {}
    with db_conn() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id=? AND tenant_id=?", (payment_id, tid)).fetchone()
        if not payment:
            raise HTTPException(404, "Payment not found.")
        if user["role"] == "customer":
            customer = conn.execute("SELECT id FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
            if not customer or customer["id"] != payment["customer_id"]:
                raise HTTPException(403, "You can only verify your own payment.")
        attempt = conn.execute("SELECT * FROM payment_attempts WHERE payment_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 1", (payment_id, tid)).fetchone()
        integration = get_tenant_integration(conn, tid, attempt["provider"]) if attempt else None
    if not attempt or not integration:
        raise HTTPException(404, "No provider payment attempt exists.")
    if attempt["provider"] == "flutterwave":
        transaction_id = str(data.get("transaction_id", "")).strip()
        if not transaction_id:
            raise HTTPException(400, "Flutterwave transaction_id is required for server-side verification.")
        verified = verify_flutterwave_transaction(integration[0]["secret_key"], transaction_id, dict(payment))
        with db_conn() as conn:
            result = settle_customer_payment(conn, dict(payment), "flutterwave", str(verified.get("id", transaction_id)))
    elif attempt["provider"] == "mtn_momo":
        result = verify_mtn_payment(integration[0], integration[1], dict(attempt), dict(payment))
        if result["status"] != "successful":
            return {"success": True, "status": result["status"], "message": "MTN has not completed this payment yet. Check again shortly."}
        with db_conn() as conn:
            settled = settle_customer_payment(conn, dict(payment), "mtn_momo", attempt["provider_reference"])
        result = {**settled, "status": "paid"}
    else:
        raise HTTPException(400, "This provider does not have a live verifier configured.")
    return {"success": True, "status": result["status"], "subscription_id": result.get("subscription_id"), "message": "Provider payment verified and service record updated."}


@app.post("/api/payments/verify-return")
def verify_flutterwave_return(request: Request, data: dict, user: dict = Depends(current_user)):
    csrf_check(request)
    tid = tenant_user(user)
    if user["role"] != "customer":
        raise HTTPException(403, "Customer payment return only.")
    tx_ref = str(data.get("tx_ref", ""))
    transaction_id = str(data.get("transaction_id", ""))
    with db_conn() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE reference=? AND tenant_id=?", (tx_ref, tid)).fetchone()
        customer = conn.execute("SELECT id FROM customers WHERE user_id=? AND tenant_id=?", (user["id"], tid)).fetchone()
        integration = get_tenant_integration(conn, tid, "flutterwave")
    if not payment or not customer or payment["customer_id"] != customer["id"] or not integration:
        raise HTTPException(404, "Payment return could not be matched to your account.")
    verified = verify_flutterwave_transaction(integration[0]["secret_key"], transaction_id, dict(payment))
    with db_conn() as conn:
        result = settle_customer_payment(conn, dict(payment), "flutterwave", str(verified.get("id", transaction_id)))
    return {"success": True, "status": result["status"], "message": "Flutterwave payment verified."}


@app.post("/api/webhooks/flutterwave/{tenant_slug}")
async def flutterwave_webhook(tenant_slug: str, request: Request):
    signature = request.headers.get("verif-hash", "")
    body = await request.json()
    transaction_id = str((body.get("data") or {}).get("id", ""))
    tx_ref = str((body.get("data") or {}).get("tx_ref", ""))
    with db_conn() as conn:
        tenant = conn.execute("SELECT id FROM tenants WHERE slug=?", (slugify(tenant_slug),)).fetchone()
        integration = get_tenant_integration(conn, tenant["id"], "flutterwave") if tenant else None
        payment = conn.execute("SELECT * FROM payments WHERE tenant_id=? AND reference=?", (tenant["id"], tx_ref)).fetchone() if tenant and tx_ref else None
    if not integration or not signature or not hmac.compare_digest(signature, integration[0]["webhook_secret"]):
        raise HTTPException(401, "Invalid Flutterwave webhook signature.")
    if not payment or not transaction_id:
        return {"success": True, "ignored": True}
    verified = verify_flutterwave_transaction(integration[0]["secret_key"], transaction_id, dict(payment))
    event_ref = str(body.get("id") or transaction_id)
    with db_conn() as conn:
        inserted = conn.execute("INSERT INTO webhook_events(id,provider,tenant_id,event_reference,status,created_at) VALUES(?,'flutterwave',?,?,'processed',?) ON CONFLICT(provider,tenant_id,event_reference) DO NOTHING",
                                (new_id("WH"), tenant["id"], event_ref, now_iso()))
        if inserted.rowcount:
            settle_customer_payment(conn, dict(payment), "flutterwave", str(verified.get("id", transaction_id)))
    return {"success": True}


@app.api_route("/api/webhooks/mtn/{tenant_slug}", methods=["POST", "PUT"])
async def mtn_webhook(tenant_slug: str, request: Request, reference_id: str = ""):
    # MTN callbacks are treated as notifications only. RIS independently queries
    # MTN's status endpoint and validates amount/currency/externalId before activation.
    body = await request.json()
    reference_id = reference_id or str(body.get("referenceId", ""))
    with db_conn() as conn:
        tenant = conn.execute("SELECT id FROM tenants WHERE slug=?", (slugify(tenant_slug),)).fetchone()
        attempt = conn.execute("SELECT * FROM payment_attempts WHERE tenant_id=? AND provider='mtn_momo' AND provider_reference=?", (tenant["id"], reference_id)).fetchone() if tenant else None
        payment = conn.execute("SELECT * FROM payments WHERE id=? AND tenant_id=?", (attempt["payment_id"], tenant["id"])).fetchone() if attempt else None
        integration = get_tenant_integration(conn, tenant["id"], "mtn_momo") if tenant else None
    if not payment or not integration:
        return {"success": True, "ignored": True}
    verified = verify_mtn_payment(integration[0], integration[1], dict(attempt), dict(payment))
    if verified["status"] == "successful":
        with db_conn() as conn:
            settle_customer_payment(conn, dict(payment), "mtn_momo", reference_id)
    return {"success": True, "provider_status": verified["status"]}


@app.get("/payments/return", include_in_schema=False)
def payment_return_page():
    return FileResponse(PROJECT_DIR / "index.html")


# ---------------------------------------------------------------------------
# Integration readiness (status only; no secret values returned)
# ---------------------------------------------------------------------------
@app.get("/api/integrations/status")
def integration_status(user: dict = Depends(need_roles("platform_admin", "owner", "admin", "network_admin"))):
    configured = {}
    if user.get("tenant_id"):
        with db_conn() as conn:
            configured = provider_status(conn, user["tenant_id"])
            router_configured = bool(conn.execute("SELECT 1 FROM router_secrets WHERE tenant_id=? LIMIT 1", (user["tenant_id"],)).fetchone())
            router_online = bool(conn.execute("SELECT 1 FROM routers WHERE tenant_id=? AND status='online' LIMIT 1", (user["tenant_id"],)).fetchone())
    else:
        router_configured = False
        router_online = False
    radius_ready = False
    if DATABASE_URL and os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() == "true":
        try:
            with db_conn() as conn:
                conn.execute("SELECT 1 FROM radcheck LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM radreply LIMIT 1").fetchone()
                conn.execute("SELECT 1 FROM nas LIMIT 1").fetchone()
            radius_ready = True
        except Exception:
            logger.warning("FreeRADIUS SQL schema is not reachable from the configured application database.")
    return {"success": True, "integrations": {
        "gmail_smtp": bool(os.getenv("SMTP_PASSWORD")),
        "africas_talking_sms": bool(os.getenv("AT_API_KEY")),
        "flutterwave_live_enabled": bool(configured.get("flutterwave", {}).get("configured")),
        "flutterwave_credentials_present": bool(configured.get("flutterwave", {}).get("configured")),
        "mtn_momo_live_enabled": bool(configured.get("mtn_momo", {}).get("configured")),
        "airtel_money_live_enabled": bool(configured.get("airtel_money", {}).get("configured")),
        "mikrotik_live_enabled": router_online,
        "mikrotik_credentials_present": router_configured,
        "freeradius_live_enabled": radius_ready,
        "freeradius_credentials_present": radius_ready,
        "database_engine": "postgresql" if DATABASE_URL else "sqlite",
        "payment_mode": PAYMENT_MODE,
        "otp_mode": "provider" if os.getenv("SMTP_PASSWORD") and os.getenv("AT_API_KEY") else "development-preview" if DEV_SHOW_OTP else "incomplete",
    }}


@app.get("/api/audit")
def audit_list(user: dict = Depends(need_roles("owner", "admin", "platform_admin"))):
    with db_conn() as conn:
        if user["role"] == "platform_admin":
            rows = conn.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100").fetchall()
        else:
            rows = conn.execute("SELECT * FROM audit_logs WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100", (tenant_user(user),)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}


def process_maintenance_once() -> dict:
    """Expire customer access and create/suspend unpaid RIS SaaS subscriptions.

    This routine is deliberately idempotent and is run by the standalone worker.
    """
    stamp = now_iso()
    expired_count = invoice_count = suspended_count = radius_retried = 0
    with db_conn() as conn:
        # A payment remains settled even if the RADIUS database was temporarily
        # unavailable. Retry active accounts on later worker cycles rather than
        # silently leaving paid subscribers permanently unprovisioned.
        if DATABASE_URL and os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() == "true":
            retry_rows = conn.execute(
                "SELECT na.id account_id,na.tenant_id,na.username,na.password_encrypted,"
                "p.* FROM network_accounts na "
                "JOIN subscriptions s ON s.customer_id=na.customer_id AND s.tenant_id=na.tenant_id AND s.status='active' "
                "JOIN packages p ON p.id=s.package_id AND p.tenant_id=s.tenant_id "
                "WHERE na.provision_status IN ('pending','failed') AND na.status='active' AND s.expires_at>? "
                "AND s.id=(SELECT s2.id FROM subscriptions s2 WHERE s2.customer_id=na.customer_id "
                "AND s2.tenant_id=na.tenant_id AND s2.status='active' AND s2.expires_at>? "
                "ORDER BY s2.expires_at DESC LIMIT 1) ORDER BY na.created_at LIMIT 100", (stamp, stamp)
            ).fetchall()
            for account in retry_rows:
                try:
                    password = decrypt_json(account["password_encrypted"])["password"]
                    result = sync_radius_account(conn, account["tenant_id"], account["username"], password, account)
                    conn.execute("UPDATE network_accounts SET provision_status=?,updated_at=? WHERE id=? AND tenant_id=?",
                                 (result, now_iso(), account["account_id"], account["tenant_id"]))
                    radius_retried += 1
                except Exception:
                    logger.exception("RADIUS provisioning retry failed for account %s", account["account_id"])

        expired = conn.execute("SELECT id,tenant_id,customer_id FROM subscriptions WHERE status='active' AND expires_at<=?", (stamp,)).fetchall()
        for subscription in expired:
            conn.execute("UPDATE subscriptions SET status='expired' WHERE id=? AND tenant_id=?", (subscription["id"], subscription["tenant_id"]))
            accounts = conn.execute("SELECT id,username FROM network_accounts WHERE customer_id=? AND tenant_id=?", (subscription["customer_id"], subscription["tenant_id"])).fetchall()
            if accounts:
                if DATABASE_URL and os.getenv("RIS_RADIUS_SQL_ENABLED", "false").lower() == "true":
                    conn.execute("SAVEPOINT radius_expiry")
                    try:
                        for account in accounts:
                            conn.execute("DELETE FROM radcheck WHERE username=?", (account["username"],))
                            conn.execute("DELETE FROM radreply WHERE username=?", (account["username"],))
                        conn.execute("RELEASE SAVEPOINT radius_expiry")
                    except Exception:
                        conn.execute("ROLLBACK TO SAVEPOINT radius_expiry")
                        conn.execute("RELEASE SAVEPOINT radius_expiry")
                        logger.exception("Could not remove expired accounts from FreeRADIUS")
                for account in accounts:
                    conn.execute("UPDATE network_accounts SET status='expired',provision_status='expired',updated_at=? WHERE id=?", (stamp, account["id"]))
            expired_count += 1

        due = conn.execute("SELECT s.*,p.monthly_price,p.annual_price,p.currency FROM tenant_subscriptions s JOIN saas_plans p ON p.code=s.plan_code WHERE s.status IN ('trial','active') AND s.next_invoice_at<=?", (stamp,)).fetchall()
        for subscription in due:
            period_start = subscription["period_end"]
            existing = conn.execute("SELECT id,status FROM platform_invoices WHERE tenant_id=? AND period_start=?", (subscription["tenant_id"], period_start)).fetchone()
            if existing:
                continue
            cycle = subscription["billing_cycle"]
            amount = int(subscription["annual_price"] if cycle == "annual" else subscription["monthly_price"])
            start_dt = datetime.fromisoformat(period_start.replace("Z", "+00:00")) if period_start else datetime.now(timezone.utc)
            end_dt = start_dt + (timedelta(days=365) if cycle == "annual" else timedelta(days=30))
            invoice_id = new_id("RINV")
            due_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            conn.execute("INSERT INTO platform_invoices(id,tenant_id,subscription_id,period_start,period_end,amount,currency,plan_code,billing_cycle,status,due_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                         (invoice_id, subscription["tenant_id"], subscription["id"], start_dt.isoformat(), end_dt.isoformat(), amount, subscription["currency"], subscription["plan_code"], cycle, "unpaid", due_at, stamp))
            if amount == 0:
                platform_invoice_paid(conn, invoice_id, "zero-cost-plan")
            else:
                conn.execute("UPDATE tenant_subscriptions SET status='past_due',grace_ends_at=?,updated_at=? WHERE id=?", ((datetime.now(timezone.utc)+timedelta(days=7)).isoformat(), stamp, subscription["id"]))
                conn.execute("UPDATE tenants SET status='past_due' WHERE id=? AND status<>'suspended'", (subscription["tenant_id"],))
            invoice_count += 1

        overdue = conn.execute("SELECT id,tenant_id FROM tenant_subscriptions WHERE status='past_due' AND grace_ends_at IS NOT NULL AND grace_ends_at<=?", (stamp,)).fetchall()
        for subscription in overdue:
            conn.execute("UPDATE tenant_subscriptions SET status='suspended',updated_at=? WHERE id=?", (stamp, subscription["id"]))
            conn.execute("UPDATE tenants SET status='suspended' WHERE id=?", (subscription["tenant_id"],))
            suspended_count += 1
    return {"radius_accounts_retried": radius_retried, "expired_customer_subscriptions": expired_count, "created_saas_invoices": invoice_count, "suspended_isp_workspaces": suspended_count}


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "message": exc.detail})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), reload=ENVIRONMENT != "production")
