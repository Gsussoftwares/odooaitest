# User Guide: Odoo 19 Tally Prime Connector

This guide explains day-to-day operations, synchronization procedures, and monitoring workflows for accounting personnel and system administrators.

---

## 1. Daily Synchronization Workflows

### Automatic Synchronization
When **Enable Automatic Tally Sync** is turned ON in settings:
1. Create and validate a Customer Invoice, Vendor Bill, or Credit Note as normal.
2. Click **Confirm** (`action_post`).
3. Odoo immediately executes the pre-flight checks and transmits the XML envelope to Tally Prime in the background.
4. If successful:
   - **Tally Status** badge updates to `Synced` (Green).
   - **Tally GUID** records the internal voucher identifier assigned by Tally.
   - **Last Tally Sync** records the exact timestamp.
5. If Tally is closed or unreachable:
   - **Tally Status** displays `Failed` (Red).
   - **Non-blocking safeguard**: Odoo confirmation is **never** blocked by a Tally sync failure. The invoice remains safely posted in Odoo and can be retried at any time.

---

## 2. Manual Synchronization & Retry Procedures

### Method A: Direct Header Button (Single Invoice)
1. Open the posted invoice or bill.
2. In the top action bar, click **"Sync to Tally"** (or **"Sync to Tally Now"**).
3. If the invoice was previously marked as synced, use **"Re-Sync (Force)"** to push updated changes.
4. A toast notification will confirm completion.

### Method B: From the "Tally Integration" Tab
1. Open the invoice and click the **Tally Integration** (or **Tally Sync**) tab.
2. Review the current synchronization status, GUID, and assigned Tally company.
3. Click **"Sync to Tally Now"** or **"Re-Sync (Force)"**.

### Method C: Payment Synchronization
1. Payments are **never automatically pushed upon validation** to prevent partial or unallocated drafts from entering Tally.
2. To synchronize a payment:
   - Open the payment record (**Invoicing → Customers → Payments**).
   - Click **"Sync to Tally"** in the header.
   - The connector pushes the corresponding balanced journal entry as a `Receipt` or `Payment` voucher.

---

## 3. Bulk Master Synchronization

When initializing a new Odoo-Tally integration or after importing bulk customer/product catalogs:

1. Navigate to **Customers → Tally Connector → Bulk Master Sync**.
2. The wizard displays the count of eligible records:
   - **Partners to sync**: Active customers and vendors.
   - **Products to sync**: Active storable and consumable goods.
3. If using multi-company, select the **Target Tally Company**.
4. Choose your sync action:
   - Click **"Sync Customers / Vendors"** to batch-push all party ledgers under Sundry Debtors/Creditors.
   - Click **"Sync Products (Goods)"** to batch-push stock items, stock groups, and units.
5. The wizard uses an optimized batch engine (30 items per payload with micro-pacing) ensuring smooth transmission without timeouts or memory spikes.

---

## 4. E-Invoice & E-Way Bill Synchronization

For Indian GST compliance:
1. Generate the E-Invoice (IRN) and E-Way Bill in Odoo.
2. Open the invoice and click **"Sync E-Invoice / E-Way Bill to Tally"**.
3. The connector transmits the IRN, Acknowledgement Number, Acknowledgement Date, E-Way Bill Number, Transporter Name, and Vehicle Number into Tally's statutory fields.
4. View transmission history under **Customers → Tally Connector → E-Invoice / E-Way Bill Logs**.

---

## 5. Reviewing Audit Logs & Diagnosing Issues

### Opening Audit Logs from an Invoice
- On any invoice or bill, click the **"Tally Logs"** stat button in the top-right button box.
- This filters the log view to show only entries for that specific document.

### Opening Full Centralized Logs
- Navigate to **Customers → Tally Connector → Sync Logs**.
- The list displays all synchronization attempts sorted by date descending.

### Inspecting an Audit Log Record
Each log record contains:
1. **Header Details**: Document name, Partner, Timestamp, Status (`Success`, `Failed`, `Skipped`).
2. **Tally Server URL & GUID**: Exact endpoint that processed the request and voucher ID.
3. **Error Diagnostics**: Specific error message parsed from Tally's response.
4. **Request XML Tab**: Complete UTF-16 XML envelope transmitted to Tally.
5. **Response XML Tab**: Raw XML response returned by Tally Prime.

### Retrying Failed Logs
- On any failed log record, click **"Retry Sync"** in the header to re-attempt transmission with one click.
