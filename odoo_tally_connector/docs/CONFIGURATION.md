# Configuration Guide: Odoo 19 Tally Prime Connector

This guide explains how to configure both **Tally Prime** and **Odoo 19** for reliable, compliant financial data synchronization.

---

## 1. Enabling Tally Prime XML HTTP Server

Tally Prime features an embedded XML Server that listens for HTTP POST requests. Follow these steps on the Windows computer running Tally Prime:

### Step 1: Open Tally Prime & Load Your Company
Launch Tally Prime and select/load the company you want to synchronize with (e.g., `Apex Global Technologies HQ`).

### Step 2: Configure Client/Server Settings
1. From the **Gateway of Tally**, press **`F1`** (Help) → **Settings** → **Connectivity**.
   *(In earlier releases: press `F12` → **Advanced Configuration**).*
2. In the **Client/Server Configuration** screen, configure the following:
   ```
   TallyPrime acts as        : Both (or Server)
   Enable ODBC Server        : No (or Yes)
   Enable XML Server         : Yes
   Port                      : 9000
   ```
3. Press **`Ctrl + A`** or press **`Enter`** through all fields to save.
4. Restart Tally Prime if prompted to bind to the port.

### Step 3: Verify Tally is Listening on Port 9000
Open Windows Command Prompt or PowerShell and run:
```powershell
netstat -an | findstr "9000"
```
**Expected Output:**
```
TCP    0.0.0.0:9000           0.0.0.0:0              LISTENING
```
This confirms that Tally Prime is active and listening for XML requests.

### Step 4: Windows Firewall Rule (Required if Odoo is on Another Computer)
If Odoo is hosted on a separate server or Linux VM, allow inbound traffic on Port 9000:
```powershell
# Run in Administrator PowerShell on the Tally machine:
New-NetFirewallRule -DisplayName "Tally Prime XML Server Port 9000" -Direction Inbound -Protocol TCP -LocalPort 9000 -Action Allow
```

---

## 2. Odoo Connector Settings Configuration

Navigate to **Invoicing (or Accounting) → Settings → Tally Prime Connector**.

| Setting Field | Configuration Key | Recommended Value | Description |
|---|---|---|---|
| **Tally Server URL** | `tally_connector.server_url` | `http://localhost:9000` *(same machine)* or `http://192.168.1.100:9000` *(LAN)* | HTTP endpoint of Tally XML Server. |
| **Tally Company Name** | `tally_connector.company_name` | `Apex Global Technologies HQ` | Exact name of the active company in Tally (case-sensitive). |
| **Enable Automatic Sync** | `tally_connector.sync_active` | `True` (Toggled ON) | Auto-syncs invoices, bills, and credit notes when confirmed (`action_post`). |
| **Include Stock Item Entries** | `tally_connector.include_inventory` | `True` (for inventory) / `False` (accounting only) | When enabled, invoice product lines generate `ALLINVENTORYENTRIES` in Tally. |
| **Auto-Create Tally Masters** | `tally_connector.auto_create_masters` | `True` | Pre-flight automatically creates missing party ledgers and stock items in Tally. |
| **Stock Group for new items**| `tally_connector.stock_item_group` | `Finished Goods` (or custom group) | Name of existing Tally Stock Group under which new items are created. |
| **Tally Godown Name** | `tally_connector.godown_name` | `Main Location` | Godown/warehouse where inventory is booked in Tally. |
| **Tally Batch Name** | `tally_connector.batch_name` | `Primary Batch` | Default batch identifier for inventory allocations. |
| **Snap voucher dates for EDU**| `tally_connector.edu_snap_voucher_dates` | `False` (for Licensed) / `True` (for EDU) | Snaps XML dates to 1st of month for Tally Educational mode testing. |
| **Include GST / Tax IDs** | `tally_connector.master_push_gst` | `True` | Pushes Tax ID / GSTIN on ledgers and HSN on stock items. |
| **Include E-Invoice / E-Way Bill** | `tally_connector.include_gst_compliance` | `True` | Transmits IRN, Ack No, Ack Date, and E-Way Bill details in sales vouchers. |

Click **"🔌 Test Connection to Tally"** to verify connectivity. A green notification confirms that Tally Prime responded successfully.

---

## 3. Setting Up Ledger Mappings

Go to **Customers → Tally Connector → Mappings → Ledger Mapping**.

Every Odoo General Ledger (GL) account that appears on invoice lines or tax lines **must be mapped** to its corresponding Tally Ledger Name.

### Standard Mapping Reference Table

| Odoo Account Code & Name | Tally Ledger Name | Tally Group | Is Party Account? | Notes |
|---|---|---|---|---|
| `1100 Accounts Receivable` | *(Dynamic Partner Name)* | `Sundry Debtors` | **✅ Yes** | Connector uses the Customer's name as the Tally ledger. |
| `2100 Accounts Payable` | *(Dynamic Partner Name)* | `Sundry Creditors` | **✅ Yes** | Connector uses the Vendor's name as the Tally ledger. |
| `4000 Sales` | `Sales Account` | `Sales Accounts` | ❌ No | Standard revenue ledger in Tally. |
| `5000 Purchase / COGS` | `Purchase Account` | `Purchase Accounts` | ❌ No | Standard direct cost ledger in Tally. |
| `2300 Output CGST` | `Output CGST` | `Duties & Taxes` | ❌ No | Central GST output tax ledger. |
| `2310 Output SGST` | `Output SGST` | `Duties & Taxes` | ❌ No | State GST output tax ledger. |
| `2320 Output IGST` | `Output IGST` | `Duties & Taxes` | ❌ No | Integrated GST output tax ledger. |
| `1600 Input CGST` | `Input CGST` | `Duties & Taxes` | ❌ No | Central GST input credit ledger. |
| `1610 Input SGST` | `Input SGST` | `Duties & Taxes` | ❌ No | State GST input credit ledger. |
| `1620 Input IGST` | `Input IGST` | `Duties & Taxes` | ❌ No | Integrated GST input credit ledger. |
| `Round Off Account` | `Round Off` | `Indirect Expenses` | ❌ No | For cash rounding entries. |

> **Crucial Rule on Party Accounts**:
> Always mark Accounts Receivable (`asset_receivable`) and Accounts Payable (`liability_payable`) with **Is Party Account = Yes**. When enabled, the connector automatically substitutes the mapped account name with the partner's legal trading name, enabling native bill-wise outstanding tracking in Tally.

---

## 4. Voucher Type Mappings

Go to **Customers → Tally Connector → Mappings → Voucher Type Mapping**.

The module automatically pre-seeds default mappings during installation:

| Odoo Document Type | Tally Voucher Type | Tally Persisted View |
|---|---|---|
| Customer Invoice (`out_invoice`) | `Sales` | `Invoice Voucher View` |
| Vendor Bill (`in_invoice`) | `Purchase` | `Invoice Voucher View` |
| Customer Credit Note (`out_refund`) | `Credit Note` | `Invoice Voucher View` |
| Vendor Debit Note (`in_refund`) | `Debit Note` | `Invoice Voucher View` |
| Customer Receipt (`out_receipt`) | `Receipt` | `Accounting Voucher View` |
| Vendor Payment (`in_receipt`) | `Payment` | `Accounting Voucher View` |

If you use customized Tally voucher types (e.g., `Tax Invoice`, `Interstate Sales`), update the **Tally Voucher Type** column to match your exact Tally configuration.

---

## 5. Unit of Measure (UoM) Mapping

Go to **Customers → Tally Connector → Mappings → UoM Mapping**.

Maps Odoo units to Tally unit symbols for inventory vouchers:

| Odoo Unit of Measure | Tally Symbol | Decimal Places |
|---|---|---|
| Units / Nos | `Nos` | 0 |
| Pieces | `pcs` | 0 |
| kg | `kg` | 3 |
| Meters | `mtr` | 2 |
| Hours | `hrs` | 2 |

---

## 6. Multi-Company Extension Configuration

*(Applies when `odoo_tally_multi_company` is installed)*

Navigate to **Customers → Tally Connector → Tally Companies**.

1. Click **New** to create a connection profile:
   - **Configuration Name**: `Mumbai Head Office` (Friendly name)
   - **Tally Company Name**: `Apex Global Technologies HQ` (Exact Tally company name)
   - **Tally Server URL**: `http://localhost:9000`
   - **Active**: `True`
2. Click **"🔌 Test Connection"** to verify status. The badge will change to **Connected** and a green ribbon will appear.
3. Repeat for additional company branches (e.g., `Bangalore Operations` on `http://192.168.1.105:9000`).

### Assigning Partners to Tally Companies
1. Open any Customer or Vendor record (**Invoicing → Customers → Customers**).
2. Go to the **Tally Integration** tab.
3. In **Assigned Tally Company**, select the target branch.
4. Any invoice or bill posted for this partner will automatically route to that specific Tally company.
