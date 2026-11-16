"""RIS integration helpers. Secrets are read from environment, never committed."""
import os, socket, subprocess
from datetime import datetime, timezone


def routeros_call(host, username, password, command, *args, timeout=5):
    """Minimal RouterOS API-SSL client using librouteros (optional dependency).
    RouterOS must have api-ssl enabled and restricted to the RIS server IP.
    """
    try:
        from librouteros import connect
        from librouteros.exceptions import TrapError
    except ImportError as exc:
        raise RuntimeError("Install librouteros to enable RouterOS integration") from exc
    api = connect(host=host, username=username, password=password, port=int(os.getenv('MIKROTIK_API_PORT','8729')), ssl=True, ssl_verify=True)
    try:
        resource = api.get_resource(command)
        return list(resource.call(*args))
    finally:
        api.close()


def radius_sql_config():
    """Returns FreeRADIUS SQL module settings from environment for operator review."""
    return {
        "dialect": os.getenv("RADIUS_SQL_DIALECT", "sqlite"),
        "server": os.getenv("RADIUS_SQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("RADIUS_SQL_PORT", "3306")),
        "database": os.getenv("RADIUS_SQL_DATABASE", "radius"),
        "username": os.getenv("RADIUS_SQL_USERNAME", "radius"),
        "configured": bool(os.getenv("RADIUS_SQL_PASSWORD")),
    }


def send_sms(phone, message):
    """Send SMS through Africa's Talking when credentials are configured."""
    username=os.getenv("AT_USERNAME"); key=os.getenv("AT_API_KEY")
    if not username or not key:
        raise RuntimeError("Africa's Talking credentials are not configured")
    import requests
    response=requests.post("https://api.africastalking.com/version1/messaging", data={"username":username,"to":phone,"message":message}, headers={"apiKey":key,"Accept":"application/json"}, timeout=20)
    response.raise_for_status()
    return response.json()
