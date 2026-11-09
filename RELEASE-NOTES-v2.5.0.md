# RIS v2.5.0 Deployment Pack

## Included
- Windows PowerShell installer and start scripts.
- macOS/Linux installer and start scripts with package-manager detection for Homebrew, apt, dnf, pacman and zypper.
- Cross-platform installation guide covering Windows, macOS, Linux, Android, iOS/iPadOS and Docker.
- Clear separation between server operating systems and mobile PWA clients.
- Updated application and package version metadata.

## Verification
- Existing backend automated test suite: 26 passed.
- Python compilation: passed.
- Frontend JavaScript syntax check: passed.
- Unix shell script syntax checks: passed.

## Important scope statement
This release improves installation and deployment guidance. It does not claim that previously identified production gaps have been solved. Live RouterOS subscriber provisioning/session control, FreeRADIUS accounting aggregation and CoA/Disconnect, complete PPPoE lifecycle, guest checkout activation, agent commission settlement, refunds/reconciliation, staff invitation, MFA/recovery, distributed job locking, production monitoring and independent security review remain outstanding or require provider/hardware credentials and end-to-end verification.

Do not use a live customer router for destructive integration tests.
