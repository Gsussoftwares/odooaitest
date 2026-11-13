# Odoo 19 Tally Prime Connector

[![Odoo Version](https://img.shields.io/badge/Odoo-19.0-714B67.svg)](https://www.odoo.com)
[![Tally Prime](https://img.shields.io/badge/Tally%20Prime-2.x%20--%205.x-00A896.svg)](https://tallysolutions.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)

**Direct Socket-to-Socket XML Synchronization between Odoo 19 and Tally Prime (Port 9000)**

The **Odoo 19 Tally Prime Connector** synchronizes posted Customer Invoices, Vendor Bills, Credit/Debit Notes, and Payments directly to Tally Prime using Tally's native HTTP XML interface. Built with zero external middleware, strict double-entry sign integrity, and an enterprise audit trail.

---

## 🌟 Key Highlights

- **Direct XML Engine (Port 9000)**: Communicates directly via HTTP POST with Tally's embedded XML server. No cloud relays, third-party desktop bridges, or recurring API subscriptions.
- **Strict Accounting Sign Enforcement**: Correctly implements Tally's inverted sign convention (Debit = Negative / `ISDEEMEDPOSITIVE=Yes`, Credit = Positive / `ISDEEMEDPOSITIVE=No`).
- **4-Stage Smart Sync Pipeline**: Automatic recovery mechanism (Create → Alter Upsert → Minimal XML → Accounting Fallback) preventing duplicate vouchers and dropped entries.
- **Master Data Pre-Flight Checks**: Auto-verifies and creates Party Ledgers (Sundry Debtors/Creditors), Stock Groups, Stock Items, and Units before posting vouchers.
- **GST & E-Way Bill Ready**: Direct transfer of GSTIN, Place of Supply, IRN, Acknowledgement Number & Date, and E-Way Bill transporter details.
- **Complete Audit Trail**: Comprehensive logging of raw UTF-16 Request and Response XML payloads with diagnostic error tracking.
- **Multi-Company Architecture**: Extensible via companion addon `odoo_tally_multi_company` for simultaneous multi-instance routing.

---

## 📋 Quick Start Guide

### 1. Prerequisites
- Odoo 19 (Community or Enterprise Edition)
- Tally Prime Release 2.x, 3.x, 4.x, or 5.x
- Python `requests` library (`pip install requests`)

### 2. Enable Tally XML Server
On the Windows computer running Tally Prime:
1. Open Tally Prime with your target company loaded.
2. Press **F1 (Help) → Settings → Connectivity**.
3. Set **Enable XML Server = Yes** on Port **9000**.
4. Confirm listening state: `netstat -an | findstr 9000`.

### 3. Configure in Odoo
1. Navigate to **Accounting (or Invoicing) → Settings → Tally Prime Connector**.
2. Enter your **Tally Server URL** (`http://localhost:9000` or LAN IP).
3. Enter your exact **Tally Company Name** (case-sensitive).
4. Click **"🔌 Test Connection to Tally"** — verify green success notification.
5. Set up your ledger mappings under **Customers → Tally Connector → Mappings → Ledger Mapping**.

---

## 📚 Complete Documentation

Detailed technical documentation is available in the [`docs/`](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/) directory:

- [Technical Architecture & Overview](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/README.md)
- [Installation Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/INSTALLATION.md)
- [Configuration Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/CONFIGURATION.md)
- [User Guide](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/USER_GUIDE.md)
- [Troubleshooting & Diagnostics](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/TROUBLESHOOTING.md)
- [Security & Hardening](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/docs/SECURITY.md)
- [Changelog & Release Notes](file:///C:/gsus_development/enterprices/server/custom_addon/odoo_tally_connector/CHANGELOG.md)

---

## 📄 License & Maintainer

- **License**: LGPL-3
- **Author / Maintainer**: GSUS
- **Target Platform**: Odoo 19.0 Community & Enterprise
