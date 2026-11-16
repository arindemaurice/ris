"""Tenant-scope helpers for RIS SaaS.

Do not derive tenant_id from an untrusted request body/header. Set it only from
verified authentication claims / membership. Use set_tenant() inside the same DB
transaction as the tenant-scoped query. This module is a guardrail/template;
wire it to the production auth and PostgreSQL session before deployment.
"""
from flask import g, abort

def require_tenant():
    tenant_id = getattr(g, "tenant_id", None)
    if not tenant_id:
        abort(401, description="Authenticated tenant context is required")
    return tenant_id

def set_tenant_on_postgres(connection, tenant_id):
    """Postgres: set tenant context transaction-locally (not SQLite)."""
    if not tenant_id:
        raise ValueError("tenant_id must come from verified auth")
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
