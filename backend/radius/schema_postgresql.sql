-- RIS-compatible FreeRADIUS PostgreSQL schema subset.
-- For production, first apply the full PostgreSQL schema.sql shipped with the
-- EXACT FreeRADIUS release installed on the RADIUS host. This file is a minimal
-- standalone subset for lab deployments and does not replace that release schema.
-- Tenant-scoped usernames are generated as <workspace>_<customer-id> by RIS.

CREATE TABLE IF NOT EXISTS radcheck (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL DEFAULT '',
  attribute TEXT NOT NULL DEFAULT '',
  op VARCHAR(2) NOT NULL DEFAULT '==',
  value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radcheck_username_idx ON radcheck(username, attribute);

CREATE TABLE IF NOT EXISTS radreply (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL DEFAULT '',
  attribute TEXT NOT NULL DEFAULT '',
  op VARCHAR(2) NOT NULL DEFAULT '=',
  value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radreply_username_idx ON radreply(username, attribute);

CREATE TABLE IF NOT EXISTS radgroupcheck (
  id BIGSERIAL PRIMARY KEY,
  groupname TEXT NOT NULL DEFAULT '',
  attribute TEXT NOT NULL DEFAULT '',
  op VARCHAR(2) NOT NULL DEFAULT '==',
  value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupcheck_groupname_idx ON radgroupcheck(groupname, attribute);

CREATE TABLE IF NOT EXISTS radgroupreply (
  id BIGSERIAL PRIMARY KEY,
  groupname TEXT NOT NULL DEFAULT '',
  attribute TEXT NOT NULL DEFAULT '',
  op VARCHAR(2) NOT NULL DEFAULT '=',
  value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupreply_groupname_idx ON radgroupreply(groupname, attribute);

CREATE TABLE IF NOT EXISTS radusergroup (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL DEFAULT '',
  groupname TEXT NOT NULL DEFAULT '',
  priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS radusergroup_username_idx ON radusergroup(username);

CREATE TABLE IF NOT EXISTS radpostauth (
  id BIGSERIAL PRIMARY KEY,
  username TEXT NOT NULL,
  pass TEXT,
  reply TEXT,
  calledstationid TEXT,
  callingstationid TEXT,
  authdate TIMESTAMPTZ NOT NULL DEFAULT now(),
  class TEXT
);

CREATE TABLE IF NOT EXISTS nas (
  id BIGSERIAL PRIMARY KEY,
  nasname TEXT NOT NULL,
  shortname TEXT NOT NULL DEFAULT '',
  type TEXT NOT NULL DEFAULT 'other',
  ports INTEGER,
  secret TEXT NOT NULL,
  server TEXT,
  community TEXT,
  description TEXT NOT NULL DEFAULT 'RIS managed NAS',
  require_ma TEXT NOT NULL DEFAULT 'auto',
  limit_proxy_state TEXT NOT NULL DEFAULT 'auto'
);
CREATE INDEX IF NOT EXISTS nas_nasname_idx ON nas(nasname);

CREATE TABLE IF NOT EXISTS nasreload (
  nasipaddress INET PRIMARY KEY,
  reloadtime TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS radacct (
  radacctid BIGSERIAL PRIMARY KEY,
  acctsessionid TEXT NOT NULL,
  acctuniqueid TEXT NOT NULL UNIQUE,
  username TEXT,
  groupname TEXT,
  realm TEXT,
  nasipaddress INET NOT NULL,
  nasportid TEXT,
  nasporttype TEXT,
  acctstarttime TIMESTAMPTZ,
  acctupdatetime TIMESTAMPTZ,
  acctstoptime TIMESTAMPTZ,
  acctinterval BIGINT,
  acctsessiontime BIGINT,
  acctauthentic TEXT,
  connectinfo_start TEXT,
  connectinfo_stop TEXT,
  acctinputoctets BIGINT,
  acctoutputoctets BIGINT,
  calledstationid TEXT,
  callingstationid TEXT,
  acctterminatecause TEXT,
  servicetype TEXT,
  framedprotocol TEXT,
  framedipaddress INET,
  framedipv6address INET,
  framedipv6prefix INET,
  framedinterfaceid TEXT,
  delegatedipv6prefix INET,
  acctstartdelay BIGINT,
  acctstopdelay BIGINT,
  class TEXT
);
CREATE INDEX IF NOT EXISTS radacct_start_user_idx ON radacct(acctstarttime, username);
CREATE INDEX IF NOT EXISTS radacct_user_idx ON radacct(username);
CREATE INDEX IF NOT EXISTS radacct_active_user_idx ON radacct(username) WHERE acctstoptime IS NULL;
