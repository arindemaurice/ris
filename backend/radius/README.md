# RIS + FreeRADIUS PostgreSQL integration

RIS does not ship or launch the FreeRADIUS daemon. Install and patch FreeRADIUS on a protected host that can reach the PostgreSQL database and the ISP's RouterOS devices.

## 1. Use the schema for your installed FreeRADIUS version

Install the full SQL schema included with the exact FreeRADIUS release and distribution you operate. FreeRADIUS versions and distro packages can ship different schema files and SQL query templates. `schema_postgresql.sql` in this folder is a deliberately small lab/reference subset for the tables RIS writes; it is **not** a production replacement for the upstream versioned schema.

For production, apply the official `schema.sql` from the installed release first and verify its SQL module queries. Only use the RIS subset on a lab database or where your DBA has confirmed the installed schema is compatible.

## 2. PostgreSQL connection

Use a dedicated role for FreeRADIUS rather than the `ris` application role. Give it only the SELECT/INSERT/UPDATE/DELETE permissions required by the SQL module on `radcheck`, `radreply`, `radgroupcheck`, `radgroupreply`, `radusergroup`, `radacct`, `radpostauth`, `nas` and related tables. RIS itself needs scoped write permissions on `radcheck`/`radreply` and `nas` for user/NAS provisioning. Do not grant either process PostgreSQL superuser.

Copy `sql-postgresql.conf.example` into the FreeRADIUS SQL module configuration and replace the host, database, role, password and pool values. Protect the file (normally root/freeradius ownership and mode 0640 or tighter).

Enable the PostgreSQL SQL module using the method for your distribution/version (for many FreeRADIUS 3 packages, enable `mods-available/sql` under `mods-enabled`). Ensure the SQL module is called in both `authorize` and `accounting` sections of the active virtual server. Do not blindly copy a configuration stanza from a different FreeRADIUS major release.

Test the daemon in foreground debug mode (`freeradius -X`, or the service-specific equivalent). Resolve all SQL module and dictionary errors before allowing subscriber traffic.

## 3. Register the RouterOS NAS

1. Give each ISP/router a unique RADIUS shared secret.
2. Add the router's source IP to the FreeRADIUS clients/NAS configuration. `nasname` must match the source address FreeRADIUS sees.
3. Permit only the intended router IPs to reach UDP 1812 (authentication) and UDP 1813 (accounting) on the RADIUS server.
4. Permit the RADIUS host to reach the router's configured incoming RADIUS message port (RIS configures UDP 1700) only when CoA/disconnect is intentionally deployed.
5. In the ISP workspace, register the RouterOS API-SSL endpoint, save its credentials and the RADIUS server IP/shared secret, test it, then run **Configure RADIUS**.

Example clients file (replace the example IP and secret; this is not a real credential):

```text
client ris-router-example {
    ipaddr = 192.0.2.10
    secret = REPLACE_WITH_A_LONG_RANDOM_UNIQUE_SHARED_SECRET
    nas_type = mikrotik
}
```

## 4. Enable RIS SQL provisioning

RIS must connect to the same PostgreSQL database containing the FreeRADIUS SQL tables:

```env
DATABASE_URL=postgresql://ris_app:REPLACE_WITH_APP_PASSWORD@db-host:5432/ris
RIS_RADIUS_SQL_ENABLED=true
```

Restart the RIS API and worker. On verified customer payment, RIS creates/updates the `radcheck` credentials and `radreply` attributes for the subscriber. On subscription expiry, the worker removes those check/reply entries.

Validate the result before serving traffic:

```sql
SELECT username, attribute, op, value FROM radcheck ORDER BY id DESC LIMIT 20;
SELECT username, attribute, op, value FROM radreply ORDER BY id DESC LIMIT 40;
SELECT nasname, shortname, type FROM nas ORDER BY id DESC LIMIT 20;
```

Use a test customer and `radtest`/`radclient` according to your installed authentication method, then verify a MikroTik login and accounting row in `radacct`.

## 5. Current limitations

- RIS writes access credentials and common RADIUS reply attributes but does not yet ingest `radacct` into its customer usage dashboard.
- Data caps currently use conservative split directional `Mikrotik-Recv-Limit` and `Mikrotik-Xmit-Limit` values. Exact combined upload+download quotas require accounting aggregation and live enforcement.
- RIS configures RouterOS incoming RADIUS messages but does not yet send, retry or confirm CoA/Disconnect packets for an already-connected session. A RouterOS `Session-Timeout` is sent for time-limited packages.
- Validate `Mikrotik-Rate-Limit`, `Port-Limit`, byte-limit attributes and simultaneous-use behavior against the exact RouterOS and FreeRADIUS versions you deploy.
- Live RouterOS hardware and FreeRADIUS SQL integration have not been tested as part of this source bundle. Start in a lab, capture logs and inspect router configuration diffs before moving to production.
