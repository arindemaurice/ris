# RIS integration setup (operator checklist)

## Included
- MikroTik RouterOS API-SSL connectivity test (`POST /api/integrations/mikrotik/test`)
- Integration configuration status (`GET /api/integrations/status`)
- FreeRADIUS SQL configuration status (`GET /api/integrations/radius/config-status`)
- Africa's Talking SMS send endpoint (`POST /api/notifications/sms`)
- Environment-variable templates and Docker Compose persistence

## Before deploying
1. Copy `backend/.env.example` to `backend/.env`; set real credentials locally. Never commit `.env`.
2. Run RouterOS v7, enable `api-ssl`, create a restricted service account, and firewall the API port so only the RIS backend can connect. Use a trusted certificate; do not disable certificate validation.
3. Install/configure FreeRADIUS on a private server, import its official SQL schema, configure RIS as a NAS client, set shared secrets, and test with `radtest`. Do not expose UDP 1812/1813 to the public internet.
4. Configure Africa's Talking account, approved sender ID and billing; start with sandbox credentials.
5. Configure Flutterwave webhooks and verify signatures plus provider-side transaction status before marking invoices paid. Never trust a browser redirect as payment confirmation.
6. Use HTTPS, strong admin authentication, role-based authorization, rate limiting, backups, and secrets management before production.

## Test locally
```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## API examples
```bash
curl http://127.0.0.1:5000/api/integrations/status
curl http://127.0.0.1:5000/api/integrations/radius/config-status
curl -X POST http://127.0.0.1:5000/api/integrations/mikrotik/test
curl -X POST http://127.0.0.1:5000/api/notifications/sms \\
  -H 'Content-Type: application/json' \\
  -d '{"phone":"+2567XXXXXXXX","message":"RIS test notification"}'
```

## Important current limitation
The integration endpoints are operator utilities, not a complete ISP automation engine. Subscriber activation/deactivation, RADIUS accounting reconciliation, recurring billing scheduler, customer-facing authentication, and secured admin RBAC still need implementation and end-to-end testing. Do not expose this backend publicly in its current state: several existing management endpoints do not yet enforce authentication/authorization.
