# Odoo 19 Tally Prime Direct XML Connector

## Technical Architecture & Product Overview

The **Odoo 19 Tally Prime Connector** (`odoo_tally_connector`) is an enterprise-grade accounting integration module that enables direct, real-time, and batch synchronization of financial documents and master records between **Odoo 19 (Community & Enterprise Editions)** and **Tally Prime (Releases 2.x through 5.x)**.

Unlike legacy connectors that rely on proprietary cloud middleware, third-party desktop agent executables, or manual Excel export/import bridges, this connector utilizes Tally Prime's native, built-in **HTTP XML Server** operating directly on **Port 9000** (or a configured LAN port).

```
+---------------------------+                +---------------------------+
|    Odoo 19 (Web/Server)   |                |   Tally Prime (Host/LAN)  |
|                           |                |                           |
|  [Customer Invoices]      |  HTTP POST     |  [XML Server: Port 9000]  |
|  [Vendor Bills]           | -------------> |                           |
|  [Credit/Debit Notes]     |   UTF-16 LE    |  [Sales Vouchers]         |
|  [Customer Receipts]      |   XML Envelope |  [Purchase Vouchers]      |
|  [Vendor Payments]        |                |  [Receipt/Payment Vch]    |
|  [Party & Stock Masters]  | <------------- |  [Sundry Debtors/Cred.]   |
|                           |  Response XML  |  [Stock Items & Units]    |
|  [tally.sync.log Audit]   |  (GUID/Errors) |                           |
+---------------------------+                +---------------------------+
```

---

## 1. Core Feature Summary

- **Direct Socket-to-Socket HTTP XML Communication**: Zero external dependencies beyond standard Python `requests`.
- **Strict Accounting Sign Convention Enforcement**: Enforces Tally's inverted ledger amount rules:
  - Debit (Asset/Expense) = Negative (`-AMOUNT`) with `ISDEEMEDPOSITIVE = Yes`
  - Credit (Liability/Income) = Positive (`+AMOUNT`) with `ISDEEMEDPOSITIVE = No`
- **Comprehensive Master Data Pre-Flight**:
  - Automatically verifies whether party ledgers (Sundry Debtors / Sundry Creditors) exist in Tally before pushing transactions.
  - Automatically verifies and creates Stock Groups, Stock Items, and Simple Units of Measure (UoM) when inventory tracking is enabled.
- **4-Stage Resilient Synchronization Engine**:
  1. **Stage 1 (Standard Create)**: Attempts initial import as a new voucher.
  2. **Stage 2 (Alter Upsert)**: Automatically switches to `ACTION="Alter"` if Tally reports an existing voucher with matching remote identifier.
  3. **Stage 3 (Minimal Tag Fallback)**: Strips non-essential legacy XML tags to bypass schema parsing issues on older Tally builds.
  4. **Stage 4 (Accounting Journal Fallback)**: For non-inventory documents, falls back to pure accounting view to ensure general ledger balances are never dropped.
- **Statutory GST, E-Invoice & E-Way Bill Integration**:
  - Pushes GSTIN, State Codes, Place of Supply, IRN, Acknowledgement Number & Date, and E-Way Bill vehicle/transporter details directly into Tally's statutory data blocks.
- **Full Audit Trail & Diagnostic XML Logging**:
  - Every transaction logs complete Request XML and Response XML, status badges (`Synced`, `Failed`, `Skipped`, `Pending`), extracted Tally GUID / Voucher Number, and diagnostic line error messages.
- **Multi-Company Architecture**:
  - Fully extensible via `odoo_tally_multi_company` to support routing transactions across multiple Tally companies and remote endpoints.

---

## 2. Supported Accounting Document Types

| Odoo Document Type | Model | Tally Prime Voucher Type | Tally Persisted View |
|---|---|---|---|
| Customer Invoice (`out_invoice`) | `account.move` | `Sales` | `Invoice Voucher View` / `Accounting Voucher View` |
| Vendor Bill (`in_invoice`) | `account.move` | `Purchase` | `Invoice Voucher View` / `Accounting Voucher View` |
| Customer Credit Note (`out_refund`) | `account.move` | `Credit Note` | `Invoice Voucher View` |
| Vendor Debit Note (`in_refund`) | `account.move` | `Debit Note` | `Invoice Voucher View` |
| Customer Receipt (`out_receipt`) | `account.move` | `Receipt` | `Accounting Voucher View` |
| Vendor Payment (`in_receipt`) | `account.move` | `Payment` | `Accounting Voucher View` |
| Payment Journal Entry (`entry`) | `account.payment` | `Receipt` / `Payment` | `Accounting Voucher View` |
| Manual Journal Entry (`entry`)* | `account.move` | `Journal` | `Accounting Voucher View` |

*\*Manual journal entries supported via `odoo_tally_multi_company` extension.*

---

## 3. System Prerequisites

### Odoo Server Environment
- **Odoo Version**: 19.0 Community Edition or 19.0 Enterprise Edition
- **Python Version**: Python 3.10, 3.11, or 3.12
- **Required Python Libraries**:
  - `requests` (Standard HTTP library, installable via `pip install requests`)
- **Required Odoo Core Addons**:
  - `account` (Invoicing & Accounting base)
  - `base_setup` (Configuration settings foundation)
  - `uom` (Units of Measure foundation)

### Tally Prime Host Environment
- **Tally Prime Version**: Release 2.0, 2.1, 3.0, 4.0, 5.0 (Silver or Gold Edition)
- **Tally Configuration**:
  - **Enable XML Server**: Set to `Yes`
  - **Server Port**: `9000` (Default, or custom port)
- **Network Connectivity**:
  - Same host: `http://localhost:9000`
  - Local Area Network (LAN): `http://<tally-server-ip>:9000`
  - Firewall: Inbound TCP Port 9000 opened on the Windows host running Tally Prime.

---

## 4. Documentation Index

Detailed setup and operational guides are provided in the following specialized documents:

- [Installation Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/INSTALLATION.md): Clean step-by-step installation instructions for Linux and Windows hosts.
- [Configuration Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/CONFIGURATION.md): Complete setup for Tally XML Server, Ledger Mappings, Voucher Mappings, and UoM.
- [User Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/USER_GUIDE.md): Operational workflows for accountants, manual retry procedures, and bulk master sync.
- [Troubleshooting Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/TROUBLESHOOTING.md): Comprehensive resolution steps for connectivity, XML errors, sign conventions, and duplicates.
- [Security & Access Control](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/SECURITY.md): RBAC permission matrix, credential safety, and network hardening guidelines.
- [Changelog](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/CHANGELOG.md): Complete version history and release notes.

---

## 5. Licensing & Commercial Terms

- **License**: LGPL-3 (GNU Lesser General Public License version 3)
- **Author / Maintainer**: GSUS
- **Target Platform**: Odoo 19.0 Community & Enterprise
