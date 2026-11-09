# RIS v1.0.0 installation and deployment guide

This is the first public early-access release. Read `PUBLISHING-CHECKLIST.md` before exposing it to the public or accepting customer payments.

This guide separates **where the RIS server runs** from **where users access RIS**. Windows, macOS and Linux can host the Python server. iOS and Android are client devices: install RIS as a Progressive Web App (PWA) from a server URL; they do not run the FastAPI/PostgreSQL/FreeRADIUS backend locally.

## 1. Requirements

### Local development server
- Windows 10/11, macOS 13+ or a supported Linux distribution.
- Python 3.11 or newer. Python 3.12 is recommended.
- Internet access for the first dependency installation.
- 2 GB RAM minimum for a small local demo; 4 GB+ recommended.
- A modern browser. Node.js is not required.

### Production server
- A Linux server or managed container host; a stable domain name.
- HTTPS termination through Caddy, Nginx or a managed load balancer.
- PostgreSQL 16 or a supported compatible version; encrypted backups.
- Separate FreeRADIUS host/service and network reachability to routers when RADIUS is used.
- SMTP, SMS and payment merchant credentials from the respective providers.
- MikroTik RouterOS API-SSL and RADIUS credentials supplied by each ISP.
- Firewall rules limited to required sources and ports.

## 2. Windows 10/11

1. Install VS Code if desired: https://code.visualstudio.com/.
2. Extract the RIS ZIP into a folder of your choice (for example `C:\RIS`). Open the extracted project folder, which contains `backend`, `frontend` and `index.html`.
3. Open PowerShell in VS Code (`Terminal` → `New Terminal`).
4. Run the installer:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\backend\install_windows.ps1
```

5. Start the app and worker:

```powershell
.\backend\start_windows.ps1
```

6. Open `http://127.0.0.1:8000`. Super Admin: `http://127.0.0.1:8000/super-admin`.
7. Keep the PowerShell window open. Ctrl+C stops the API and the script stops its worker.

The installer can offer Python 3.12 through `winget` if Python is missing. If `winget` is unavailable, install Python 3.11+ from https://www.python.org/downloads/windows/ and rerun.

## 3. macOS

1. Open Terminal. Install Homebrew if needed: https://brew.sh/.
2. Extract the ZIP and `cd` into `ris-main`.
3. Run:

```bash
chmod +x backend/install_unix.sh backend/start_unix.sh
./backend/install_unix.sh
./backend/start_unix.sh
```

The installer checks for Python 3.11+. If missing, it uses Homebrew to install Python 3.12. Open `http://127.0.0.1:8000` in Safari, Chrome or Firefox.

## 4. Linux distributions

Supported package-manager paths include Ubuntu/Debian (`apt`), Fedora/RHEL-family (`dnf`), Arch (`pacman`) and openSUSE (`zypper`). Ensure the distribution's Python package is 3.11+ and includes venv support. On distributions whose repositories ship an older Python, install Python 3.11+ using the distribution's supported method before running the installer.

```bash
chmod +x backend/install_unix.sh backend/start_unix.sh
./backend/install_unix.sh
./backend/start_unix.sh
```

The installer may call `sudo` to install missing system packages. Review your package manager prompts. For headless servers, use a process supervisor (systemd/container orchestrator) rather than leaving a terminal session open.

## 5. Android phones and tablets

Android is a RIS client, not a backend host. First run RIS on a computer/server and make it reachable using a trusted HTTPS domain. Open that URL in Chrome, tap the browser menu and choose **Install app** or **Add to Home screen** when available. Open the RIS icon and sign in. The same server account and ISP workspace are used.

For a temporary same-Wi-Fi LAN test only, the server can be configured to bind to its LAN interface and the phone can open `http://SERVER-LAN-IP:8000`. This is not encrypted and must not be used over public networks or with real customer/payment data. The default launcher binds to localhost for safety.

## 6. iPhone and iPad (iOS/iPadOS)

iOS/iPadOS cannot host the RIS Python backend. Deploy RIS to a server with HTTPS, open the domain in Safari, tap **Share** → **Add to Home Screen**, then launch the icon. PWA features vary by iOS version. The app still requires a network connection for login, billing, payments and network operations.

## 7. Docker deployment (staging/production foundation)

Install Docker Desktop on Windows/macOS or Docker Engine plus the Compose plugin on Linux. From the repository root:

```bash
cd backend
python3 setup.py       # only if backend/.env does not exist
```

Review `backend/.env`, set production secrets, SMTP/SMS credentials and the public HTTPS URL, then from the repository root run:

```bash
docker compose --env-file backend/.env -f backend/docker-compose.yml up --build -d
```

Inspect logs:

```bash
docker compose --env-file backend/.env -f backend/docker-compose.yml logs -f ris worker db
```

The Compose stack includes RIS, PostgreSQL and the maintenance worker. It does **not** install FreeRADIUS, provision physical MikroTik devices, create payment merchant accounts, configure DNS or provide TLS certificates. Those are separate infrastructure and provider tasks. Review firewall exposure and put the app behind HTTPS before public access.

## 8. First administrator credentials

The bootstrap administrator display name defaults to `Maurice Arinde`. The setup script generates a unique high-entropy password and writes it to `backend/.env` as `RIS_BOOTSTRAP_ADMIN_PASSWORD`. Open that private file locally to retrieve it. The password is intentionally not printed in this README or committed to the ZIP. Do not upload `.env`, share screenshots of it or commit it to Git. Rotate the password after first login and keep a secure backup of the environment file and encryption key.

If `.env` already exists, setup will not overwrite it. To reset access, use the documented administrative password-reset procedure or arrange a controlled recovery against a backup. Do not delete `.env` on an installation that contains encrypted router/payment credentials: doing so may make those credentials permanently unreadable.

## 9. Mobile/desktop support and offline behavior

RIS is a responsive web app/PWA. The server is authoritative. The service worker caches static interface assets only; it does not cache authentication, customer, billing, payment or router API data. Offline access therefore does not mean offline billing or network administration.

## 10. Integrations that require external setup

| Integration | What the installer does | What the operator must supply/test |
|---|---|---|
| PostgreSQL | Docker Compose can start PostgreSQL | Production backups, access policy, migration and restore tests |
| FreeRADIUS | Includes reference SQL schema/config notes | Install daemon, use matching upstream schema, SQL module, NAS clients, auth/accounting tests |
| MikroTik | Includes RouterOS API-SSL integration foundation | Router IP, API-SSL credentials, RADIUS secret, lab provisioning and rollback tests |
| Flutterwave | Includes provider adapter | Approved merchant account, test/live keys, webhook, transaction verification |
| MTN MoMo | Includes provider adapter foundation | API user/key/subscription key, callback reachability and live certification |
| Airtel Money | No live collection adapter in this release | Country-specific API onboarding and implementation/verification |
| Email/SMS | Includes SMTP and Africa's Talking configuration paths | Real sender credentials, sender approval and delivery tests |

A local demo payment is simulated and never proves that money was collected or that a router granted internet access.

## 11. First login and local smoke test

After starting the server, open `http://127.0.0.1:8000`. The platform administrator display name defaults to Maurice Arinde; enter the email supplied to setup as the alternate login identifier. Retrieve the generated password from `backend/.env` (`RIS_BOOTSTRAP_ADMIN_PASSWORD`) and change it after signing in. The development setup shows OTP previews and uses simulated payments; this is not live email/SMS or a real money transaction.

Check `http://127.0.0.1:8000/api/health`. The API documentation is available at `/api/docs` in development mode only.

## 12. Verification

From `backend` after installation:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m py_compile app.py worker.py setup.py
```

Then check `/api/health`, sign in as the platform admin, create a test ISP and customer, and test customer CRUD. Run real payment, RADIUS accounting, CoA/Disconnect and MikroTik provisioning only in a lab environment first.

## 13. Troubleshooting

- **Python not found:** install Python 3.11+ and reopen the terminal.
- **Missing package:** use the project's virtual environment and rerun the installer; do not mix global Python installations.
- **Port 8000 in use:** stop the other service or change the port consistently in the launch command and browser URL.
- **Cannot access from phone:** `127.0.0.1` means the server device itself. Use a properly deployed HTTPS domain, or a temporary same-LAN setup with explicit firewall/bind configuration.
- **Super Admin login fails:** verify the administrator name/email and the `RIS_BOOTSTRAP_ADMIN_PASSWORD` value in the correct installation's private `.env`.
- **Router/RADIUS test fails:** confirm routing, firewall, TLS certificate, RouterOS API service, NAS source IP, shared secret and FreeRADIUS logs. Do not troubleshoot by changing the live customer router blindly.
