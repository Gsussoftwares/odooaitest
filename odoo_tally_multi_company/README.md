# Tally Multi-Company Connector (Extension)

[![Odoo Version](https://img.shields.io/badge/Odoo-19.0-714B67.svg)](https://www.odoo.com)
[![Base Dependency](https://img.shields.io/badge/Requires-odoo__tally__connector-00A896.svg)](https://apps.odoo.com)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)

**Multi-Endpoint & Multi-Instance Extension for Odoo 19 Tally Prime Connector**

The **Tally Multi-Company Connector** (`odoo_tally_multi_company`) extends the core `odoo_tally_connector` base module to connect multiple Tally Prime company instances simultaneously across different ports, IP addresses, or branches, with intelligent partner-to-company destination routing.

> **Important**: This is an extension addon. It requires `odoo_tally_connector` to be installed.

---

## 🚀 Key Extension Features

- **Multi-Endpoint Management**: Maintain unlimited active Tally Prime connection profiles via `tally.company` records.
- **Port & Host Flexibility**: Connect to multiple Tally instances on the same machine (e.g., ports 9000, 9001) or across remote LAN/VPN servers.
- **Partner-Based Company Routing**: Assign Customers and Vendors to specific Tally companies. Invoices, bills, and payments automatically route to the corresponding destination.
- **Per-Company Connection Testing**: Dedicated live connection verification per profile with real-time status badges and ribbons.
- **Unified Tally Integration Tab**: Replaces the single-company tab on Invoices, Bills, Payments, and Partners with a unified multi-company dashboard.
- **High-Speed Batch Master Sync**: Enhanced batch engine with micro-pacing for tunnel-safe bulk synchronization of customer and product masters.

---

## 📋 Installation & Setup

1. Ensure the base addon `odoo_tally_connector` is installed in your Odoo 19 environment.
2. Install `odoo_tally_multi_company` via **Apps → Search "Tally Multi-Company Connector" → Install**.
3. Navigate to **Customers → Tally Connector → Tally Companies**.
4. Configure your connection profiles and click **Test Connection** to verify live connectivity.
5. Assign target Tally companies on your Customer/Vendor records under the **Tally Integration** tab.

---

## 📄 License & Maintainer

- **License**: LGPL-3
- **Author / Maintainer**: GSUS
- **Target Platform**: Odoo 19.0 Community & Enterprise
- **Dependencies**: `account`, `odoo_tally_connector`
