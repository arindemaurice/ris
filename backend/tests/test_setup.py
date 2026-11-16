"""Release packaging regression tests for first-run configuration."""
import os
import subprocess
import sys
from pathlib import Path


def test_setup_template_is_included_and_generates_private_secrets(tmp_path):
    source = Path(__file__).resolve().parents[1]
    target = tmp_path / "backend"
    target.mkdir()
    for filename in ("setup.py", ".env.example"):
        (target / filename).write_bytes((source / filename).read_bytes())

    completed = subprocess.run(
        [sys.executable, "setup.py"],
        cwd=target,
        input="admin@ris.example\nRIS Release Admin\n",
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    env_text = (target / ".env").read_text(encoding="utf-8")
    assert "RIS_BOOTSTRAP_ADMIN_EMAIL=admin@ris.example" in env_text
    assert "RIS_BOOTSTRAP_ADMIN_NAME=RIS Release Admin" in env_text
    assert "GENERATE_" not in env_text
    assert "RIS_SECRET_KEY=" in env_text
    assert "RIS_PASSWORD_PEPPER=" in env_text
    assert "RIS_OTP_PEPPER=" in env_text
    assert "RIS_CREDENTIALS_KEY=" in env_text
    assert "RIS_BOOTSTRAP_ADMIN_PASSWORD='" in env_text
    assert "initial password is saved" in completed.stdout.lower()


def test_setup_does_not_overwrite_existing_environment(tmp_path):
    source = Path(__file__).resolve().parents[1]
    target = tmp_path / "backend"
    target.mkdir()
    (target / "setup.py").write_bytes((source / "setup.py").read_bytes())
    env_file = target / ".env"
    env_file.write_text("KEEP_ME=unchanged\n", encoding="utf-8")
    subprocess.run([sys.executable, "setup.py"], cwd=target, text=True, capture_output=True, check=True)
    assert env_file.read_text(encoding="utf-8") == "KEEP_ME=unchanged\n"
