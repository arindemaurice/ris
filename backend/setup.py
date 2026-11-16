"""Create a local .env with strong random keys and the initial RIS platform admin."""
from pathlib import Path
import secrets
import string
import base64

HERE = Path(__file__).resolve().parent
ENV = HERE / ".env"
EXAMPLE = HERE / ".env.example"


def random_secret(n=64):
    return secrets.token_urlsafe(n)


def random_password(length=24):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    while True:
        value = ''.join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value) and any(c in "!@#$%^&*()-_=+" for c in value):
            return value


def main():
    if ENV.exists():
        print(f"Configuration already exists: {ENV}")
        print("Existing secrets were not overwritten.")
        return
    content = EXAMPLE.read_text(encoding="utf-8")
    default_admin_email = "admin@example.com"
    try:
        admin_email = input(f"Initial RIS platform administrator email [{default_admin_email}]: ").strip().lower()
    except EOFError:
        admin_email = ""
    admin_email = admin_email or default_admin_email
    if "@" not in admin_email or "." not in admin_email.rsplit("@", 1)[-1]:
        raise SystemExit("Please provide a valid administrator email address and run setup again.")
    content = content.replace("RIS_BOOTSTRAP_ADMIN_EMAIL=" + default_admin_email, "RIS_BOOTSTRAP_ADMIN_EMAIL=" + admin_email)
    try:
        admin_name = input("Initial RIS platform administrator name [Maurice Arinde]: ").strip()
    except EOFError:
        admin_name = ""
    admin_name = admin_name or "Maurice Arinde"
    content = content.replace("RIS_BOOTSTRAP_ADMIN_NAME=Maurice Arinde", "RIS_BOOTSTRAP_ADMIN_NAME=" + admin_name.replace("\n", " ").strip())
    replacements = {
        "GENERATE_A_RANDOM_SECRET": random_secret(),
        "GENERATE_A_DIFFERENT_RANDOM_SECRET": random_secret(),
        "GENERATE_ANOTHER_RANDOM_SECRET": random_secret(),
        "GENERATE_A_FERNET_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "GENERATE_A_POSTGRES_PASSWORD": random_secret(36),
        "GENERATE_A_STRONG_PASSWORD": random_password(),
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    # Single-quote the generated bootstrap password so dotenv/Compose preserve
    # special characters such as $, # and % without interpolation.
    content = content.replace(
        "RIS_BOOTSTRAP_ADMIN_PASSWORD=" + replacements["GENERATE_A_STRONG_PASSWORD"],
        "RIS_BOOTSTRAP_ADMIN_PASSWORD='" + replacements["GENERATE_A_STRONG_PASSWORD"] + "'",
    )
    ENV.write_text(content, encoding="utf-8")
    print("RIS local configuration created.")
    admin_email = next((line.split("=", 1)[1].strip() for line in content.splitlines() if line.startswith("RIS_BOOTSTRAP_ADMIN_EMAIL=")), "admin@example.com")
    print(f"Platform administrator: {admin_name} ({admin_email})")
    print("The initial password is saved in this private .env file as RIS_BOOTSTRAP_ADMIN_PASSWORD.")
    print("Local OTP preview and simulated payments are enabled for development only.")
    print("A separate Fernet key was generated for encrypted provider/router credentials.")
    print("A PostgreSQL password was generated for the Docker Compose deployment.")
    print("Do not commit backend/.env to GitHub.")


if __name__ == "__main__":
    main()
