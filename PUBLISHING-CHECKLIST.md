# RIS v1.0.0 - First publication and deployment checklist

This guide explains the difference between publishing the source code, running a private test installation and launching a public production service. Completing one does not automatically complete the others.

## A. Before publishing the source

1. Decide the repository visibility: private for a controlled pilot, or public if you intend anyone to inspect/download the source.
2. Decide the software licence before making the repository public. No licence is included in this package; do not imply that others may copy, modify or resell it until you choose and add a licence.
3. Review `SECURITY.md`, `CODE-AUDIT-AND-ROADMAP.md` and `TRIAL-TEST-PLAN.md`.
4. Confirm that `backend/.env`, databases, backups, logs, `.venv`, provider keys and router credentials are not in the release. The ZIP contains `.env.example`, not a live `.env`.
5. Keep the generated platform-admin password, `RIS_SECRET_KEY`, `RIS_PASSWORD_PEPPER`, `RIS_OTP_PEPPER`, `RIS_CREDENTIALS_KEY` and PostgreSQL password private.
6. Run the tests using the instructions in `INSTALLATION-GUIDE.md`.
7. Publish the release archive and checksum together. Do not upload a working server's `.env` or database.

## B. Local installation for a first test

Use `INSTALLATION-GUIDE.md` for Windows, macOS or Linux. The shortest Windows path is:

1. Install Python 3.11+.
2. Extract the ZIP into a folder, for example `C:\RIS`.
3. Open PowerShell in that folder.
4. Run:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .\backend\install_windows.ps1
   .\backend\start_windows.ps1
   ```

5. Open `http://127.0.0.1:8000`.
6. Read the initial password from `backend/.env` (`RIS_BOOTSTRAP_ADMIN_PASSWORD`). The initial administrator name defaults to Maurice Arinde and the email is the one entered during setup.
7. Sign in and immediately change the initial password. Keep the `.env` file backed up securely.
8. Test using demo data only. Development OTP previews and simulated payments do not send real messages or collect money.

## C. Public hosting requirements

For a real public website, use a Linux VPS or managed container host. Do not host the production backend on an ordinary Android/iPhone device or an unattended personal laptop.

Minimum starting point for a small controlled pilot:

- Ubuntu Server 24.04 LTS or another supported Linux distribution.
- 2 vCPU and 4 GB RAM minimum; more capacity depends on ISP/customer load.
- A domain name and DNS access.
- Docker Engine and Docker Compose plugin, or Python 3.11+ with a managed PostgreSQL service.
- PostgreSQL with encrypted off-site backups and tested restore procedure.
- HTTPS certificate and reverse proxy (Caddy or Nginx).
- Firewall allowing public TCP 80/443 only; keep PostgreSQL, RADIUS and RouterOS management ports private/restricted.
- SMTP/SMS provider accounts and approved sender identities if verification messages are required.
- Payment merchant accounts, webhook URLs and provider test/live credentials before accepting real payments.
- A separate FreeRADIUS service and an isolated MikroTik test router before activating network automation.

## D. Public deployment using Docker Compose

1. Point your domain's DNS A/AAAA record to the VPS address.
2. Install Docker Engine and the Compose plugin.
3. Copy the release folder to the server and enter the project directory.
4. Create the private environment file:

   ```bash
   cd backend
   python3 setup.py
   cd ..
   ```

   Enter a real administrator email and name. The script creates `backend/.env` with unique secrets and a random initial password. Save the password securely.

5. Edit `backend/.env`. Set at least:

   ```env
   RIS_ENV=production
   RIS_DEV_SHOW_OTP=false
   RIS_PAYMENT_MODE=live
   PUBLIC_BASE_URL=https://ris.example.com
   RIS_ALLOWED_ORIGINS=https://ris.example.com
   ```

   Keep all generated secrets unchanged and private. Configure SMTP/SMS/payment values only after obtaining valid provider credentials. Do not enable live payment mode until the merchant adapter, webhook and settlement have been tested end-to-end.

6. Start the application stack:

   ```bash
   docker compose --env-file backend/.env -f backend/docker-compose.yml up --build -d
   ```

7. The application binds to `127.0.0.1:8000` on the host. Put Caddy or Nginx in front of it and proxy HTTPS traffic to `127.0.0.1:8000`. Do not expose port 8000 directly to the internet.
8. Example Caddy site block (replace the domain):

   ```caddyfile
   ris.example.com {
       encode zstd gzip
       reverse_proxy 127.0.0.1:8000
   }
   ```

   Caddy must be installed and configured on the host with DNS pointing correctly so it can obtain and renew a TLS certificate. This example is not a substitute for firewall configuration.

9. Check status and logs:

   ```bash
   docker compose --env-file backend/.env -f backend/docker-compose.yml ps
   docker compose --env-file backend/.env -f backend/docker-compose.yml logs -f ris worker db
   curl -fsS http://127.0.0.1:8000/api/health
   ```

10. Open `https://ris.example.com`. Sign in as the platform administrator and change the generated password.
11. Set up encrypted backups and test a restore before entering real customer data.

## E. Android and iPhone access

The backend runs on the server. Android/iPhone are client devices:

- Android: open the HTTPS domain in Chrome, use the browser menu and select Install app/Add to Home screen.
- iPhone/iPad: open the HTTPS domain in Safari, tap Share, then Add to Home Screen.
- Users sign in with their ISP workspace/customer account. Data remains on the server.

## F. Integrations required before commercial ISP operations

| Area | Required action before live customer use |
|---|---|
| Payment | Complete merchant onboarding; configure secrets and callbacks; verify amount, currency, reference, idempotency and refund paths in sandbox and production. |
| Email/SMS | Configure SMTP/Africa's Talking credentials, sender approval, delivery monitoring and retry policy. |
| FreeRADIUS | Install a supported FreeRADIUS version, apply the matching SQL schema, configure clients/NAS, test authentication and accounting. |
| MikroTik | Create a least-privilege RouterOS account, use API-SSL, test against a lab router and validate rollback. Never begin on the live RB951 serving customers. |
| Hotspot/PPPoE | Complete subscriber provisioning, renewal, suspension, session disconnect and expiry verification. |
| Finance | Test invoices, duplicate callbacks, partial payments, refunds, commissions and reconciliation. |
| Security | Complete independent security review, tenant-isolation testing, MFA/recovery, rate limiting, monitoring and incident-response procedures. |

## G. Go-live decision

Do not announce the platform as fully automated or accept customer money for automated access until all relevant items in section F pass real end-to-end tests. The v1.0.0 application is an initial public early-access release, not a certification that every external integration is live.
