# RIS v2.6.0 - Payment settlement and network monitoring

## Implemented

- Added a database uniqueness constraint ensuring one customer subscription per settled payment.
- Changed payment settlement to use a conditional status transition as its concurrency gate.
- Repeated successful payment verification returns the existing subscription reference.
- Added maintenance-worker retries for active network accounts that were not provisioned in FreeRADIUS because the SQL integration was unavailable or failed temporarily.
- Added regression coverage for repeated payment verification and duplicate-subscription prevention.

## Verification

- Python compilation checks.
- JavaScript syntax check.
- Unix shell syntax checks.
- Full automated backend test suite.

## Important limitations

This is a payment-settlement and recovery hardening release, not a complete ISP operations release. Public guest captive portal live checkout, MikroTik subscriber lifecycle, live session listing/disconnect, FreeRADIUS accounting aggregation, CoA/Disconnect acknowledgement/retry, PPPoE lifecycle, agent commissions, reconciliation/refunds and production security certification remain incomplete. Real provider credentials, PostgreSQL/FreeRADIUS deployment and an isolated RouterOS lab are required for live integration tests.
