# Troubleshooting Guide: Odoo 19 Tally Prime Connector

This guide outlines root causes, error diagnostics, and step-by-step corrective actions for all common operational issues.

---

## 1. Connectivity & Network Errors

### ❌ "Cannot connect to Tally at http://localhost:9000"
- **Cause 1**: Tally Prime application is not open on the host machine.
  - **Fix**: Launch Tally Prime and open your target company.
- **Cause 2**: XML Server is disabled in Tally Prime.
  - **Fix**: In Tally Prime, press **F1 (Help) → Settings → Connectivity**. Verify **Enable XML Server = Yes** on Port 9000.
- **Cause 3**: Odoo is hosted on a remote server/VM, but the setting is still pointing to `localhost`.
  - **Fix**: In Odoo settings, change `http://localhost:9000` to the actual LAN IP address of the Windows machine running Tally Prime (e.g. `http://192.168.1.100:9000`).
- **Cause 4**: Windows Defender Firewall is blocking inbound connections on Port 9000.
  - **Fix**: On the Windows machine running Tally, run as Administrator:
    ```powershell
    New-NetFirewallRule -DisplayName "Tally XML Server" -Direction Inbound -Protocol TCP -LocalPort 9000 -Action Allow
    ```

### ❌ "Request to Tally timed out after 10 seconds"
- **Cause**: Heavy report execution in Tally, network latency over WAN/VPN, or Tally modal dialog blocking the thread.
- **Fix**: Verify Tally Prime is idle and not displaying an unaccepted modal dialog or prompt. If syncing large bulk masters, use the batch master sync wizard which paces requests automatically.

---

## 2. Configuration & Mapping Errors

### ❌ "Tally Company Name is not configured"
- **Cause**: The company field in settings or the Assigned Tally Company in multi-company is blank.
- **Fix**: Open **Accounting → Settings → Tally Prime Connector** and type the exact company name matching Tally's title bar.

### ❌ "Account code [XXXX] not mapped in Tally Ledger Mapping"
- **Cause**: An invoice line or tax line uses a GL account that has no active record in `tally.ledger.map`.
- **Fix**: Navigate to **Customers → Tally Connector → Mappings → Ledger Mapping**. Click **New**, select the account, enter its exact Tally Ledger Name, and set the appropriate Tally Group.

### ❌ "Tally Stock Group does not exist!" (or "Stock Group 'Products' does not exist!")
- **Cause**: Odoo is attempting to auto-create a stock item under a Stock Group that does not exist in Tally Prime.
- **Fix**: In Tally Prime, open **Gateway of Tally → Create (or Alter) → Stock Groups**. Check your existing group names (e.g., `Finished Goods` or `Raw Materials`). In Odoo Settings, enter that exact name into **Stock Group for new items**.

---

## 3. Accounting & XML Validation Errors

### ❌ "Voucher date is missing"
- **Cause**: This error occurs predominantly in **TallyPrime Educational Mode (EDU)**. Tally EDU only permits voucher dates falling on the **1st, 2nd, or last day of the month**.
- **Fix**:
  - For testing in Tally EDU: Enable **"Snap voucher dates for TallyPrime EDU"** in Odoo Settings. This temporarily snaps the XML date tag to the 1st of the month without modifying your actual Odoo invoice dates.
  - For production: Use a licensed Tally Prime Gold/Silver edition with the financial year period opened (Alt + F2).

### ❌ Entries appear in Tally with inverted amounts (Negative Sales / Positive Receivables)
- **Cause**: Inverted sign convention misconfiguration.
- **Fix**:
  - In Tally XML, Debit entries must be negative (`-AMOUNT`), and Credit entries must be positive (`+AMOUNT`).
  - Verify that Accounts Receivable and Accounts Payable accounts are mapped with **"Is Party Account? = Yes"** in **Ledger Mapping**.
  - Inspect the **Request XML** in the Sync Log to verify the `AMOUNT` and `ISDEEMEDPOSITIVE` tags.

### ❌ Duplicate Voucher or RemoteID Conflict
- **Cause**: An invoice with the same name was already created in Tally, but Odoo's local `tally_guid` field was cleared or empty.
- **Fix**:
  - The connector's **Stage 2 Smart Sync** automatically retries as `ACTION="Alter"`.
  - Alternatively, if you wish to do a clean re-send: delete the entry from Tally Prime, click **"Re-Sync (Force)"** on the invoice in Odoo.

---

## 4. Multi-Company Extension Errors

### ❌ "Sync skipped: No Tally Company assigned to document"
- **Cause**: The partner on the invoice is not assigned to any Tally Company, and no default company is active.
- **Fix**: Open the Customer/Vendor form, navigate to **Tally Integration**, and choose an **Assigned Tally Company**. Alternatively, select the destination company directly on the invoice form under the **Tally Integration** tab.

### ❌ "Sync skipped: Assigned Tally Company is inactive"
- **Cause**: The connection profile for the target company is toggled inactive (`active = False`).
- **Fix**: Navigate to **Customers → Tally Connector → Tally Companies**, open the profile, and toggle **Active = ON**.
