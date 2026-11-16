import sys
import os
import sqlite3
from pathlib import Path

# Supply deterministic bootstrap credentials for isolated automated tests.
os.environ.setdefault("RIS_BOOTSTRAP_ADMIN_EMAIL", "test-admin@ris.local")
os.environ.setdefault("RIS_BOOTSTRAP_ADMIN_PASSWORD", "Test!AdminPassphrase2026")

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as ris


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ris, "DB_PATH", str(tmp_path / "ris-test.db"))
    with TestClient(ris.app) as test_client:
        yield test_client


def csrf(client):
    return {"X-CSRF-Token": client.get("/api/csrf").json()["csrf_token"]}


def register_isp(client, slug, email, phone):
    headers = csrf(client)
    started = client.post("/api/auth/register/isp/start", headers=headers, json={
        "isp_name": f"{slug.title()} Internet", "workspace": slug,
        "full_name": "Workspace Owner", "email": email, "phone": phone,
        "password": "Test!Passphrase2026",
    })
    assert started.status_code == 200, started.text
    payload = started.json()
    codes = payload["development_only_codes"]
    with sqlite3.connect(ris.DB_PATH) as conn:
        delivery_rows = conn.execute("SELECT channel,status FROM otp_delivery_logs WHERE challenge_id=? ORDER BY channel", (payload["challenge_id"],)).fetchall()
    assert {row[0] for row in delivery_rows} == {"email", "sms"}
    assert all(row[1] == "development_preview" for row in delivery_rows)
    verified = client.post("/api/auth/register/isp/verify", headers=headers, json={
        "challenge_id": payload["challenge_id"],
        "email_code": codes["email"], "sms_code": codes["sms"],
    })
    assert verified.status_code == 200, verified.text
    return verified.json()


def test_isp_signup_and_owner_dashboard(client):
    register_isp(client, "alpha-net", "owner@alpha.test", "+256700001001")
    me = client.get("/api/me").json()["user"]
    assert me["role"] == "owner"
    assert me["tenant"]["slug"] == "alpha-net"
    dash = client.get("/api/dashboard").json()
    assert dash["scope"] == "tenant"
    assert dash["summary"]["customers"] == 0
    assert client.get("/").status_code == 200
    assert client.get("/api/health").json()["database"] == "connected"


def test_both_otp_channels_required(client):
    h = csrf(client)
    start = client.post("/api/auth/register/isp/start", headers=h, json={
        "isp_name": "Verify Net", "workspace": "verify-net", "full_name": "Owner Person",
        "email": "otp@verify.test", "phone": "+256700001002", "password": "Test!Passphrase2026",
    })
    data = start.json()
    codes = data["development_only_codes"]
    wrong = client.post("/api/auth/register/isp/verify", headers=h, json={
        "challenge_id": data["challenge_id"], "email_code": codes["email"], "sms_code": "000000",
    })
    assert wrong.status_code == 400
    good = client.post("/api/auth/register/isp/verify", headers=h, json={
        "challenge_id": data["challenge_id"], "email_code": codes["email"], "sms_code": codes["sms"],
    })
    assert good.status_code == 200


def test_customer_registration_and_demo_purchase(client):
    register_isp(client, "beta-net", "owner@beta.test", "+256700001003")
    client.post("/api/auth/logout", headers=csrf(client), json={})
    h = csrf(client)
    start = client.post("/api/auth/register/customer/start", headers=h, json={
        "tenant_slug": "beta-net", "full_name": "Subscriber One", "email": "sub@beta.test",
        "phone": "+256700001004", "password": "Test!Passphrase2026",
    })
    assert start.status_code == 200
    body = start.json(); codes = body["development_only_codes"]
    verified = client.post("/api/auth/register/customer/verify", headers=h, json={
        "challenge_id": body["challenge_id"], "email_code": codes["email"], "sms_code": codes["sms"],
    })
    assert verified.status_code == 200
    packages = client.get("/api/portal/packages").json()["items"]
    assert packages
    purchase = client.post("/api/portal/purchase", headers=csrf(client), json={"package_id": packages[0]["id"]})
    assert purchase.status_code == 200
    payment_id = purchase.json()["payment_id"]
    confirmation = client.post(f"/api/payments/{payment_id}/demo-confirm", headers=csrf(client), json={})
    assert confirmation.status_code == 200
    summary = client.get("/api/portal/summary").json()
    assert len(summary["subscriptions"]) == 1
    assert summary["payments"][0]["status"] == "paid"
    assert "No real money" in confirmation.json()["message"]


def test_tenant_data_isolation(client, tmp_path):
    register_isp(client, "alpha-space", "owner@alpha-space.test", "+256700001010")
    a = TestClient(ris.app)
    a.cookies.update(client.cookies)
    add = a.post("/api/customers", headers=csrf(a), json={"name": "Alpha Subscriber", "email": "person@alpha.test"})
    assert add.status_code == 200
    alpha_rows = a.get("/api/customers").json()["items"]
    assert len(alpha_rows) == 1

    b = TestClient(ris.app)
    register_isp(b, "beta-space", "owner@beta-space.test", "+256700001011")
    beta_rows = b.get("/api/customers").json()["items"]
    assert beta_rows == []


def test_mutating_request_requires_csrf(client):
    register_isp(client, "csrf-net", "owner@csrf.test", "+256700001020")
    response = client.post("/api/customers", json={"name": "No CSRF"})
    assert response.status_code == 403


def test_public_paths_do_not_expose_backend_files(client):
    assert client.get("/backend/app.py").status_code == 404
    assert client.get("/.env").status_code == 404
    assert client.get("/assets/app.css").status_code == 200
    assert client.get("/assets/app.js").status_code == 200
    assert client.get("/assets/ris-logo.png").status_code == 200
    assert client.get("/portal/sample-isp").status_code == 200


def test_user_can_change_password_and_old_password_stops_working(client):
    register_isp(client, "password-net", "owner@password.test", "+256700001030")
    changed = client.post("/api/auth/change-password", headers=csrf(client), json={
        "current_password": "Test!Passphrase2026",
        "new_password": "New!SecurePassphrase2030",
    })
    assert changed.status_code == 200
    client.post("/api/auth/logout", headers=csrf(client), json={})
    bad = client.post("/api/auth/login", headers=csrf(client), json={
        "email": "owner@password.test", "tenant_slug": "password-net", "password": "Test!Passphrase2026",
    })
    assert bad.status_code == 401
    good = client.post("/api/auth/login", headers=csrf(client), json={
        "email": "owner@password.test", "tenant_slug": "password-net", "password": "New!SecurePassphrase2030",
    })
    assert good.status_code == 200


def test_otp_attempt_counter_persists_and_challenge_locks(client):
    headers = csrf(client)
    started = client.post("/api/auth/register/isp/start", headers=headers, json={
        "isp_name": "Locked Net", "workspace": "locked-net", "full_name": "Owner Person",
        "email": "locked@otp.test", "phone": "+256700001040", "password": "Test!Passphrase2026",
    })
    challenge_id = started.json()["challenge_id"]
    for _ in range(ris.OTP_MAX_ATTEMPTS):
        wrong = client.post("/api/auth/register/isp/verify", headers=headers, json={
            "challenge_id": challenge_id, "email_code": "000000", "sms_code": "111111",
        })
        assert wrong.status_code == 400
    locked = client.post("/api/auth/register/isp/verify", headers=headers, json={
        "challenge_id": challenge_id, "email_code": "000000", "sms_code": "111111",
    })
    assert locked.status_code == 429


def test_tenant_payment_credentials_are_encrypted_and_never_returned(client):
    register_isp(client, "secure-gateway", "owner@gateway.test", "+256700001050")
    response = client.put("/api/tenant/integrations/flutterwave", headers=csrf(client), json={
        "secrets": {"secret_key": "FLW_TEST_SECRET_DO_NOT_EXPOSE", "webhook_secret": "FLW_WEBHOOK_SECRET_DO_NOT_EXPOSE"},
        "config": {"environment": "test"},
    })
    assert response.status_code == 200, response.text
    status = client.get("/api/tenant/integrations")
    assert status.status_code == 200
    assert status.json()["providers"]["flutterwave"]["configured"] is True
    assert "FLW_TEST_SECRET_DO_NOT_EXPOSE" not in status.text
    with sqlite3.connect(ris.DB_PATH) as conn:
        encrypted = conn.execute("SELECT secrets_encrypted FROM tenant_integrations WHERE provider='flutterwave'").fetchone()[0]
    assert "FLW_TEST_SECRET_DO_NOT_EXPOSE" not in encrypted
    assert "FLW_WEBHOOK_SECRET_DO_NOT_EXPOSE" not in encrypted


def test_saas_plan_billing_and_feature_entitlements(client):
    register_isp(client, "plan-upgrade", "owner@plan.test", "+256700001051")
    h = csrf(client)
    blocked_agent = client.post("/api/agents", headers=h, json={"name": "Starter Agent", "commission_rate": 5})
    assert blocked_agent.status_code == 402

    chosen = client.post("/api/tenant/billing/choose-plan", headers=h, json={"plan_code": "growth", "billing_cycle": "monthly"})
    assert chosen.status_code == 200, chosen.text
    paid = client.post(f"/api/tenant/billing/invoices/{chosen.json()['invoice_id']}/demo-confirm", headers=h, json={})
    assert paid.status_code == 200
    billing = client.get("/api/tenant/billing").json()
    assert billing["subscription"]["plan_code"] == "growth"
    assert billing["subscription"]["status"] == "active"
    usage = client.get("/api/tenant/usage").json()
    assert usage["limits"]["customers"] == 3000
    agent = client.post("/api/agents", headers=csrf(client), json={"name": "Growth Agent", "commission_rate": 7.5})
    assert agent.status_code == 200, agent.text


def test_worker_creates_single_invoice_and_marks_trial_past_due(client):
    register_isp(client, "renewal-worker", "owner@renewal.test", "+256700001052")
    with ris.db_conn() as conn:
        conn.execute("UPDATE tenant_subscriptions SET next_invoice_at=? WHERE tenant_id=(SELECT id FROM tenants WHERE slug='renewal-worker')", ("2000-01-01T00:00:00+00:00",))
    result = ris.process_maintenance_once()
    assert result["created_saas_invoices"] == 1
    with ris.db_conn() as conn:
        sub = conn.execute("SELECT status FROM tenant_subscriptions WHERE tenant_id=(SELECT id FROM tenants WHERE slug='renewal-worker')").fetchone()
        count = conn.execute("SELECT COUNT(*) n FROM platform_invoices WHERE tenant_id=(SELECT id FROM tenants WHERE slug='renewal-worker')").fetchone()["n"]
    assert sub["status"] == "past_due"
    assert count == 1
    # Running the worker again must not duplicate the same billing period invoice.
    again = ris.process_maintenance_once()
    assert again["created_saas_invoices"] == 0
    with ris.db_conn() as conn:
        count = conn.execute("SELECT COUNT(*) n FROM platform_invoices WHERE tenant_id=(SELECT id FROM tenants WHERE slug='renewal-worker')").fetchone()["n"]
    assert count == 1


def test_router_plan_limit_is_enforced(client):
    register_isp(client, "router-limit", "owner@routerlimit.test", "+256700001053")
    h = csrf(client)
    for index in range(3):
        result = client.post("/api/routers", headers=h, json={"name": f"Router {index+1}", "host": f"10.10.0.{index+1}", "api_port": 8729})
        assert result.status_code == 200, result.text
    over_limit = client.post("/api/routers", headers=h, json={"name": "Router Four", "host": "10.10.0.4", "api_port": 8729})
    assert over_limit.status_code == 402


def test_flutterwave_checkout_is_verified_before_activation(client, monkeypatch):
    register_isp(client, "fw-verify", "owner@fw.test", "+256700001060")
    saved = client.put("/api/tenant/integrations/flutterwave", headers=csrf(client), json={
        "secrets": {"secret_key": "flw-test-secret", "webhook_secret": "fw-webhook-secret"},
        "config": {"environment": "test"},
    })
    assert saved.status_code == 200, saved.text
    client.post("/api/auth/logout", headers=csrf(client), json={})
    h = csrf(client)
    start = client.post("/api/auth/register/customer/start", headers=h, json={
        "tenant_slug": "fw-verify", "full_name": "Paying Customer", "email": "customer@fw.test",
        "phone": "+256700001061", "password": "Test!Passphrase2026",
    })
    codes = start.json()["development_only_codes"]
    verified_customer = client.post("/api/auth/register/customer/verify", headers=h, json={
        "challenge_id": start.json()["challenge_id"], "email_code": codes["email"], "sms_code": codes["sms"],
    })
    assert verified_customer.status_code == 200
    package = client.get("/api/portal/packages").json()["items"][0]
    purchase = client.post("/api/portal/purchase", headers=csrf(client), json={"package_id": package["id"]})
    payment_id = purchase.json()["payment_id"]
    with sqlite3.connect(ris.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        payment = dict(conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())

    class FakeResponse:
        status_code = 200
        def __init__(self, payload): self.payload = payload
        def raise_for_status(self): return None
        def json(self): return self.payload

    gateway_calls = []
    def fake_gateway_post(*args, **kwargs):
        gateway_calls.append((args, kwargs))
        return FakeResponse({"status": "success", "data": {"link": "https://checkout.test/session"}})
    monkeypatch.setattr(ris.requests, "post", fake_gateway_post)
    checkout = client.post(f"/api/payments/{payment_id}/checkout", headers=csrf(client), json={"provider": "flutterwave"})
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["checkout_url"] == "https://checkout.test/session"
    repeated = client.post(f"/api/payments/{payment_id}/checkout", headers=csrf(client), json={"provider": "flutterwave"})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["provider_reference"] == checkout.json()["provider_reference"]
    assert len(gateway_calls) == 1, "a repeated click must not send a second gateway request"

    transaction_payload = {"status": "success", "data": {"status": "successful", "tx_ref": payment["reference"], "amount": payment["amount_minor"], "currency": payment["currency"], "id": 123456}}
    monkeypatch.setattr(ris.requests, "get", lambda *a, **k: FakeResponse(transaction_payload))
    bad_payload = {**transaction_payload, "data": {**transaction_payload["data"], "amount": payment["amount_minor"] + 100}}
    monkeypatch.setattr(ris.requests, "get", lambda *a, **k: FakeResponse(bad_payload))
    bad = client.post(f"/api/payments/{payment_id}/verify", headers=csrf(client), json={"transaction_id": "123456"})
    assert bad.status_code == 400
    assert client.get("/api/portal/summary").json()["subscriptions"] == []

    monkeypatch.setattr(ris.requests, "get", lambda *a, **k: FakeResponse(transaction_payload))
    good = client.post(f"/api/payments/{payment_id}/verify", headers=csrf(client), json={"transaction_id": "123456"})
    assert good.status_code == 200, good.text
    summary = client.get("/api/portal/summary").json()
    assert len(summary["subscriptions"]) == 1
    assert summary["payments"][0]["status"] == "paid"

    # Repeated provider verification/webhook delivery must not create another
    # subscription or lose the original subscription reference.
    repeated_verify = client.post(f"/api/payments/{payment_id}/verify", headers=csrf(client), json={"transaction_id": "123456"})
    assert repeated_verify.status_code == 200, repeated_verify.text
    assert repeated_verify.json()["subscription_id"] == summary["subscriptions"][0]["id"]
    with sqlite3.connect(ris.DB_PATH) as conn:
        assert conn.execute("SELECT COUNT(*) FROM subscriptions WHERE payment_id=?", (payment_id,)).fetchone()[0] == 1


def test_routeros_api_test_and_radius_configuration(client, monkeypatch):
    import types
    register_isp(client, "routeros-lab", "owner@routeros.test", "+256700001070")
    router = client.post("/api/routers", headers=csrf(client), json={"name": "Lab Router", "host": "192.0.2.1", "api_port": 8729})
    assert router.status_code == 200
    router_id = router.json()["id"]
    saved = client.put(f"/api/routers/{router_id}/credentials", headers=csrf(client), json={
        "api_username": "ris-api", "api_password": "Router!Secret", "radius_server": "192.0.2.10", "radius_secret": "Radius!Secret",
    })
    assert saved.status_code == 200

    operations = []
    class Resource:
        def __init__(self, path): self.path = path
        def get(self, **filters):
            if self.path == "/system/resource": return [{"version": "7.15.2"}]
            if self.path == "/system/identity": return [{"name": "RIS-LAB"}]
            if self.path == "/ip/hotspot/profile": return [{".id": "*1", "name": "default"}]
            if self.path in ("/ppp/aaa", "/radius/incoming"): return [{".id": "*2"}]
            return []
        def set(self, **values): operations.append((self.path, "set", values))
        def add(self, **values): operations.append((self.path, "add", values))
    class FakeAPI:
        def get_resource(self, path): return Resource(path)
    class FakePool:
        def __init__(self, *args, **kwargs): operations.append(("pool", "connect", kwargs))
        def get_api(self): return FakeAPI()
        def disconnect(self): operations.append(("pool", "disconnect", {}))
    monkeypatch.setitem(sys.modules, "routeros_api", types.SimpleNamespace(RouterOsApiPool=FakePool))

    tested = client.post(f"/api/routers/{router_id}/test", headers=csrf(client), json={})
    assert tested.status_code == 200, tested.text
    assert tested.json()["identity"] == "RIS-LAB"
    configured = client.post(f"/api/routers/{router_id}/configure-radius", headers=csrf(client), json={})
    assert configured.status_code == 200, configured.text
    assert any(op[0] == "/radius" and op[1] == "add" for op in operations)
    assert any(op[0] == "/ip/hotspot/profile" and op[1] == "set" and op[2].get("use_radius") == "yes" for op in operations)
    assert any(op[0] == "/ppp/aaa" and op[1] == "set" for op in operations)
    assert any(op[0] == "/radius/incoming" and op[1] == "set" for op in operations)
    radius_args = [op[2] for op in operations if op[0] == "/radius" and op[1] in ("add", "set")]
    assert radius_args and all("accounting" not in args for args in radius_args)


def test_router_live_status_reads_health_and_sessions_without_mutating_router(client, monkeypatch):
    import sys, types
    register_isp(client, "router-live", "owner@router-live.test", "+256700001071")
    router = client.post("/api/routers", headers=csrf(client), json={"name": "Lab router", "host": "192.0.2.1", "api_port": 8729})
    router_id = router.json()["id"]
    saved = client.put(f"/api/routers/{router_id}/credentials", headers=csrf(client), json={
        "api_username": "ris-readonly", "api_password": "test-secret",
    })
    assert saved.status_code == 200
    operations = []
    class FakeResource:
        def __init__(self, path): self.path = path
        def get(self):
            operations.append((self.path, "get"))
            return {
                "/system/resource": [{"version": "7.24.4", "uptime": "2d3h", "cpu-load": "4", "free-memory": "1000", "total-memory": "2000"}],
                "/system/identity": [{"name": "RIS-LAB"}],
                "/ip/hotspot/active": [{"user": "client-1", "address": "10.10.0.25", "uptime": "00:10:00", "mac-address": "AA:BB:CC:DD:EE:FF"}],
                "/ppp/active": [{"name": "pppoe-1", "address": "10.10.0.26", "uptime": "00:20:00", "caller-id": "AA:BB:CC:DD:EE:00"}],
            }.get(self.path, [])
    class FakeAPI:
        def get_resource(self, path): return FakeResource(path)
    class FakePool:
        def __init__(self, *args, **kwargs): pass
        def get_api(self): return FakeAPI()
        def disconnect(self): operations.append(("pool", "disconnect"))
    monkeypatch.setitem(sys.modules, "routeros_api", types.SimpleNamespace(RouterOsApiPool=FakePool))
    result = client.get(f"/api/routers/{router_id}/status")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["identity"] == "RIS-LAB"
    assert body["hotspot_sessions"] == 1 and body["pppoe_sessions"] == 1
    assert {x["service"] for x in body["sessions"]} == {"hotspot", "pppoe"}
    assert all("password" not in x for x in body["sessions"])
    assert all(method == "get" or path == "pool" for path, method in operations)


def test_radius_reply_attributes_follow_routeros_directions(client, monkeypatch):
    class CaptureConnection:
        def __init__(self): self.statements = []
        def execute(self, sql, params=()): self.statements.append((sql, params)); return self
    monkeypatch.setattr(ris, "DATABASE_URL", "postgresql://test/ris")
    monkeypatch.setenv("RIS_RADIUS_SQL_ENABLED", "true")
    conn = CaptureConnection()
    package = {"speed_down_kbps": 20000, "speed_up_kbps": 5000, "validity_hours": 2, "data_limit_mb": 100, "device_limit": 3}
    result = ris.sync_radius_account(conn, "tenant-1", "workspace_user1", "secret", package)
    assert result == "provisioned"
    statements = [(sql, params) for sql, params in conn.statements]
    rate = next(params[1] for sql, params in statements if "Mikrotik-Rate-Limit" in sql)
    assert rate == "5000k/20000k"
    attrs = [params[1] for sql, params in statements if "radreply" in sql and "INSERT" in sql and len(params) > 1]
    assert "Mikrotik-Recv-Limit" in attrs and "Mikrotik-Xmit-Limit" in attrs
    assert "Mikrotik-Total-Limit" not in attrs
    assert any("Port-Limit" in sql for sql, _ in statements)


def test_platform_saas_checkout_is_idempotent(client, monkeypatch):
    register_isp(client, "saas-checkout", "owner@saas-checkout.test", "+256700001080")
    selected = client.post("/api/tenant/billing/choose-plan", headers=csrf(client), json={
        "plan_code": "growth", "billing_cycle": "monthly",
    })
    assert selected.status_code == 200, selected.text
    invoice_id = selected.json()["invoice_id"]
    monkeypatch.setenv("RIS_PLATFORM_FLW_SECRET_KEY", "ris-platform-test-key")

    class FakeResponse:
        status_code = 200
        def raise_for_status(self): return None
        def json(self): return {"status": "success", "data": {"link": "https://checkout.test/ris-plan"}}

    calls = []
    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()
    monkeypatch.setattr(ris.requests, "post", fake_post)

    first = client.post(f"/api/tenant/billing/invoices/{invoice_id}/checkout", headers=csrf(client), json={})
    assert first.status_code == 200, first.text
    second = client.post(f"/api/tenant/billing/invoices/{invoice_id}/checkout", headers=csrf(client), json={})
    assert second.status_code == 200, second.text
    assert second.json()["checkout_url"] == first.json()["checkout_url"]
    assert len(calls) == 1
    with ris.db_conn() as conn:
        records = conn.execute("SELECT * FROM platform_payments WHERE invoice_id=?", (invoice_id,)).fetchall()
    assert len(records) == 1
    assert records[0]["status"] == "pending"


def test_generated_platform_admin_credentials_sign_in(client):
    assert ris.BOOTSTRAP_EMAIL == "test-admin@ris.local"
    assert ris.BOOTSTRAP_PASSWORD
    response = client.post("/api/auth/login", headers=csrf(client), json={
        "email": ris.BOOTSTRAP_EMAIL,
        "password": ris.BOOTSTRAP_PASSWORD,
    })
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "platform_admin"
    assert client.get("/api/dashboard").json()["scope"] == "platform"


def test_customer_cannot_access_staff_package_or_voucher_lists(client):
    register_isp(client, "role-net", "owner@role.test", "+256700001101")
    client.post("/api/auth/logout", headers=csrf(client), json={})
    headers = csrf(client)
    start = client.post("/api/auth/register/customer/start", headers=headers, json={
        "tenant_slug": "role-net", "full_name": "Portal Customer", "email": "portal@role.test",
        "phone": "+256700001102", "password": "Test!Passphrase2026",
    })
    body = start.json()
    verified = client.post("/api/auth/register/customer/verify", headers=headers, json={
        "challenge_id": body["challenge_id"], "email_code": body["development_only_codes"]["email"],
        "sms_code": body["development_only_codes"]["sms"],
    })
    assert verified.status_code == 200
    assert client.get("/api/packages").status_code == 403
    assert client.get("/api/vouchers").status_code == 403
    assert client.get("/api/portal/packages").status_code == 200


def test_customer_cannot_attach_another_tenants_package(client):
    register_isp(client, "first-net", "owner@first.test", "+256700001111")
    with sqlite3.connect(ris.DB_PATH) as conn:
        first_tenant = conn.execute("SELECT id FROM tenants WHERE slug='first-net'").fetchone()[0]
        first_package = conn.execute("SELECT id FROM packages WHERE tenant_id=? LIMIT 1", (first_tenant,)).fetchone()[0]
    client.post("/api/auth/logout", headers=csrf(client), json={})
    second = TestClient(ris.app)
    register_isp(second, "second-net", "owner@second.test", "+256700001112")
    response = second.post("/api/customers", headers=csrf(second), json={
        "name": "Cross Tenant Attempt", "package_id": first_package,
    })
    assert response.status_code == 404
    assert second.get("/api/customers").json()["items"] == []


def test_tenant_captive_portal_configuration_and_trial_checkout(client):
    register_isp(client, "portal-alpha", "owner@portal-alpha.test", "+256700001020")
    headers = csrf(client)
    portal = client.get("/api/tenant/captive-portal")
    assert portal.status_code == 200, portal.text
    assert portal.json()["portal_url"] == "/portal/portal-alpha"

    saved = client.put("/api/tenant/captive-portal", headers=headers, json={
        "enabled": True,
        "config": {
            "headline": "Welcome to Portal Alpha",
            "welcome_message": "Choose a test plan.",
            "primary_color": "#123abc",
            "background_color": "#071a2e",
            "show_packages": True,
            "show_voucher": True,
        },
    })
    assert saved.status_code == 200, saved.text
    public = client.get("/api/public/portal/portal-alpha")
    assert public.status_code == 200, public.text
    assert public.json()["config"]["headline"] == "Welcome to Portal Alpha"
    assert public.json()["packages"]

    package_id = public.json()["packages"][0]["id"]
    order = client.post("/api/public/portal/portal-alpha/purchase", headers=csrf(client), json={
        "package_id": package_id, "name": "Trial Subscriber", "phone": "+256700001021",
    })
    assert order.status_code == 200, order.text
    assert "No money" in order.json()["message"]
    confirmation = client.post(
        f"/api/public/portal/portal-alpha/purchase/{order.json()['payment_id']}/confirm",
        headers=csrf(client), json={"demo_token": order.json()["demo_token"]},
    )
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["status"] == "paid"
    assert "no router" in confirmation.json()["message"].lower()

    # The one-time trial confirmation token cannot be reused for another activation.
    repeated = client.post(
        f"/api/public/portal/portal-alpha/purchase/{order.json()['payment_id']}/confirm",
        headers=csrf(client), json={"demo_token": order.json()["demo_token"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "paid"


def test_captive_portal_rejects_cross_tenant_and_invalid_branding(client):
    register_isp(client, "portal-one", "owner@portal-one.test", "+256700001030")
    headers = csrf(client)
    invalid = client.put("/api/tenant/captive-portal", headers=headers, json={
        "config": {"primary_color": "not-a-colour"}, "enabled": True,
    })
    assert invalid.status_code == 400
    client.post("/api/auth/logout", headers=csrf(client), json={})
    register_isp(client, "portal-two", "owner@portal-two.test", "+256700001031")
    assert client.get("/api/public/portal/portal-one").status_code == 200
    assert client.get("/api/tenant/captive-portal").json()["tenant"]["slug"] == "portal-two"


def test_trial_voucher_redemption_is_one_time(client):
    register_isp(client, "voucher-alpha", "owner@voucher-alpha.test", "+256700001040")
    packages = client.get("/api/packages").json()["items"]
    package_id = packages[0]["id"]
    generated = client.post("/api/vouchers/generate", headers=csrf(client), json={"package_id": package_id, "count": 1})
    assert generated.status_code == 200, generated.text
    code = generated.json()["codes"][0]
    redeemed = client.post("/api/public/portal/voucher-alpha/redeem-voucher", headers=csrf(client), json={"code": code, "name": "Voucher Trial User"})
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["status"] == "active"
    again = client.post("/api/public/portal/voucher-alpha/redeem-voucher", headers=csrf(client), json={"code": code})
    assert again.status_code == 400


def test_public_portal_page_is_served_and_live_voucher_flow_is_gated(client, monkeypatch):
    register_isp(client, "portal-page", "owner@portal-page.test", "+256700001050")
    page = client.get("/portal/portal-page")
    assert page.status_code == 200
    assert 'id="app"' in page.text
    assert "/assets/app.js" in page.text
    monkeypatch.setattr(ris, "ENVIRONMENT", "production")
    blocked = client.post("/api/public/portal/portal-page/redeem-voucher", headers=csrf(client), json={"code": "NOTREAL"})
    assert blocked.status_code == 403


def test_customer_lifecycle_search_edit_and_archive(client):
    register_isp(client, "customer-ops", "owner@customer-ops.test", "+256700009001")
    h = csrf(client)
    created = client.post("/api/customers", headers=h, json={
        "name": "Test Hotspot User", "email": "hotspot@customer-ops.test",
        "phone": "+256700009002", "service_type": "hotspot",
    })
    assert created.status_code == 200, created.text
    customer_id = created.json()["id"]
    found = client.get("/api/customers?q=Hotspot").json()["items"]
    assert len(found) == 1 and found[0]["id"] == customer_id
    updated = client.patch(f"/api/customers/{customer_id}", headers=csrf(client), json={
        "name": "Updated Hotspot User", "status": "suspended",
    })
    assert updated.status_code == 200, updated.text
    assert client.get("/api/customers?q=Updated").json()["items"][0]["status"] == "suspended"
    archived = client.delete(f"/api/customers/{customer_id}", headers=csrf(client))
    assert archived.status_code == 200, archived.text
    assert client.get("/api/customers").json()["items"] == []
    history = client.get("/api/customers?include_archived=true&status=archived").json()["items"]
    assert len(history) == 1 and history[0]["id"] == customer_id
    restored = client.post(f"/api/customers/{customer_id}/restore", headers=csrf(client), json={})
    assert restored.status_code == 200
    restored_row = client.get("/api/customers").json()["items"][0]
    assert restored_row["status"] == "pending"


def test_platform_admin_username_and_global_customer_management(client):
    admin = client.post("/api/auth/login", headers=csrf(client), json={
        "email": "Maurice Arinde", "password": "Test!AdminPassphrase2026",
    })
    assert admin.status_code == 200, admin.text
    assert admin.json()["user"]["role"] == "platform_admin"
    owner = TestClient(ris.app)
    register_isp(owner, "global-ops", "owner@global-ops.test", "+256700009010")
    tenant = owner.get("/api/me").json()["user"]["tenant"]
    platform_client = TestClient(ris.app)
    platform_login = platform_client.post("/api/auth/login", headers=csrf(platform_client), json={
        "email": "Maurice Arinde", "password": "Test!AdminPassphrase2026",
    })
    assert platform_login.status_code == 200
    created = platform_client.post("/api/platform/customers", headers=csrf(platform_client), json={
        "tenant_id": tenant["id"], "name": "Global Admin Customer", "phone": "+256700009011",
        "service_type": "hotspot",
    })
    assert created.status_code == 200, created.text
    rows = platform_client.get("/api/platform/customers?tenant_id=" + tenant["id"]).json()["items"]
    assert len(rows) == 1 and rows[0]["name"] == "Global Admin Customer"
    changed = platform_client.patch("/api/platform/customers/" + created.json()["id"], headers=csrf(platform_client), json={"status": "suspended"})
    assert changed.status_code == 200
    assert platform_client.get("/api/platform/customers?tenant_id=" + tenant["id"]).json()["items"][0]["status"] == "suspended"


def test_platform_customer_console_is_platform_admin_only(client):
    register_isp(client, "no-global-access", "owner@no-global.test", "+256700009020")
    denied = client.get("/api/platform/customers")
    assert denied.status_code == 403
    assert client.get("/super-admin").status_code == 200
