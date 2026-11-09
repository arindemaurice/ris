# RIS v2.3.0 Trial Test Plan

This plan is for a local, isolated trial. Use invented customer information and test phone numbers. Do not enter real payment credentials or connect a production router during this trial.

## A. Start the system

1. Extract the ZIP into a new folder.
2. Open `ris-main` in VS Code.
3. Open a terminal at the project root and run `cd backend`.
4. Run `run_all_windows.bat` on Windows. On macOS/Linux use `./run_linux_mac.sh` from `backend`.
5. Wait for Uvicorn to report that it is listening on `http://127.0.0.1:8000`.
6. Open `http://127.0.0.1:8000`.
7. Register a new ISP workspace. In local development, the email and SMS OTP codes are shown as development preview codes.
8. Keep the initial RIS platform administrator account separate from the ISP owner account.

## B. Test the ISP owner's workflow

1. Sign in as the ISP owner.
2. Confirm the dashboard belongs to the newly created ISP workspace.
3. Open **Services & packages**. A sample `Starter 2GB Daily` hotspot package is created for a new ISP. Edit or add a test package if needed.
4. Open **Vouchers** and generate one or more vouchers for an active hotspot package. Copy the generated codes into a local test note.
5. Open **Captive portal**.
6. Change the headline, welcome text, primary/background colours and footer. Toggle package and voucher visibility to verify the settings.
7. Save and publish the portal.
8. Use **Preview customer portal** or open `/portal/<your-workspace-slug>` in a private browser window.
9. Confirm that the portal displays only this ISP's brand and active hotspot packages.

## C. Test customer package purchase

1. On the public portal, select **Test purchase** for a package.
2. Enter a fictional test customer's name.
3. Read the confirmation prompt. It must clearly state that no money will be collected.
4. Confirm the simulated payment.
5. Confirm that the portal reports an active trial subscription and an expiry time.
6. Sign back into the ISP owner workspace.
7. Check Customers, Invoices, Payments and the dashboard. The test customer, invoice and paid trial payment should be recorded under this ISP only.
8. Confirm the trial purchase did not create a real mobile-money transaction, RADIUS credential or router change.

## D. Test voucher redemption

1. Return to the public portal.
2. Enter a fictional name and one unused voucher from section B.
3. Redeem it once. The portal should report an active trial subscription and package expiry.
4. Try the same voucher again. The second attempt must be rejected as already used or unavailable.
5. Check the owner's voucher list. Its status should now be `used`.

## E. Test tenant isolation

1. Register a second ISP using a different email, phone and workspace slug.
2. Create a package and voucher in the second workspace.
3. Confirm the second ISP's portal URL shows only its own package catalogue and brand.
4. Confirm the first ISP cannot see the second ISP's customers, vouchers, invoices, payments or portal settings.
5. Confirm that the second ISP cannot see the first ISP's data.

## F. Test responsive access

- Test owner workspace and public portal at 320, 375, 768, 1024 and 1440 CSS-pixel widths using browser responsive tools.
- Test Chrome and Edge on Windows; Safari on iPhone/iPad; Chrome on Android; and Firefox where available.
- For a phone on the same Wi-Fi as the development computer, start a separate trial server bound to `0.0.0.0` and open the computer's LAN IP on the phone. Allow the port through the local firewall only on a trusted private network. Do not expose the trial server to the public internet.
- PWA installation requires HTTPS on a deployed host; `localhost` is allowed for local development. A plain LAN HTTP address is not a secure PWA origin.

## G. Pass/fail record

Record each case as PASS or FAIL, include the browser/OS and attach the error text or screenshot for failures:

| Case | Expected result |
|---|---|
| Owner registration | New ISP workspace and owner account created |
| Portal settings | Settings persist after refresh |
| Public portal | Correct tenant brand and active packages appear |
| Trial package purchase | Invoice, payment and subscription records created; no real payment |
| Trial voucher redemption | First use succeeds; second use is rejected |
| Tenant isolation | No cross-ISP data is visible |
| Mobile layout | No clipped controls or horizontal page overflow |
| Live router safety | Trial workflows make no router changes |
| Live payment safety | Trial workflows make no provider calls |

## Trial limitations

This release provides a testable captive-portal customer journey and owner configuration. Trial purchase and voucher redemption create database records only. They do not provide real internet connectivity. Live public payment checkout, signed provider webhook verification, router hotspot provisioning, FreeRADIUS authentication/accounting, CoA/disconnect, PPPoE activation, reseller commissions and production monitoring require further implementation and end-to-end testing.


## v2.4.0 customer and platform-owner regression checks

1. Run the first-time setup and keep the generated `backend/.env` private. The platform administrator display name defaults to `Maurice Arinde`; the password is randomly generated and is not a shared hard-coded value.
2. Open `/super-admin`. Confirm that the platform administrator can sign in using the configured display name and bootstrap password. Confirm that an ISP owner cannot access platform customer APIs.
3. Register two test ISP workspaces. Sign in as the platform administrator and open **All customers**. Create a customer under ISP A, filter the list to ISP A, and confirm the record appears only under that tenant.
4. Search by customer name, phone, email and record ID. Confirm that the ISP name/workspace is shown for every global customer result.
5. Suspend and reactivate a test customer. Confirm the customer record status changes. With FreeRADIUS SQL enabled in a lab only, verify that authorization rows are removed on suspension and recreated on reactivation.
6. Archive a test customer. Confirm the customer disappears from the normal customer directory while invoices, payments and audit history remain.
7. Sign in as ISP A owner. Confirm that customer search/edit/archive is restricted to ISP A and that a guessed customer ID from ISP B returns 404.
8. Do not use the production MikroTik for destructive provisioning tests. Active RADIUS sessions are not yet disconnected by CoA/Disconnect in this release.
