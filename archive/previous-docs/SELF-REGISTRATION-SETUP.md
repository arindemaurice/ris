# RIS Hotspot Customer Self-Registration

New endpoint flow:
1. `POST /api/auth/register/start` accepts `full_name`, `email`, `phone`, `password`.
2. RIS generates separate six-digit codes and stores only hashes in SQLite with a 10-minute expiry.
3. Email code is sent via Gmail SMTP; SMS code is sent through Africa's Talking.
4. `POST /api/auth/register/verify` accepts `challenge_id`, `email_code`, `sms_code` and creates the `hotspot_users` account only after both match.

## Configure
- Copy `.env.example` to `.env` (never commit `.env`).
- Gmail: enable 2-Step Verification and create an App Password. Put it in `SMTP_PASSWORD`; normal Gmail password will not work.
- Africa's Talking: set API key, username and approved sender ID. Sandbox may not deliver to arbitrary phone numbers; use live credentials for real SMS.
- Set `RIS_OTP_PEPPER` and `RIS_PASSWORD_SALT` to long unique random values before deployment.
- Ensure the API is HTTPS and configure `RIS_ALLOWED_ORIGINS` for the deployed portal domain.

## Notes
- Codes are never returned to the browser or logged by the app.
- Challenge expiration and attempt limits are enforced.
- This implementation creates a customer account record. Integration with tenant_id, RADIUS/MikroTik provisioning, login sessions, resend OTP, rate limiting by IP/phone, and a tenant-specific registration policy must be completed before production multi-tenant rollout.
