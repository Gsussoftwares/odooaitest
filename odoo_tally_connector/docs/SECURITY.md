# Security & Hardening Guide: Odoo 19 Tally Prime Connector

This document details the security model, role-based access controls (RBAC), network architecture recommendations, and data privacy safeguards implemented in the connector.

---

## 1. Role-Based Access Control (RBAC) Matrix

The connector integrates strictly with Odoo's native financial security groups:

| Model | Group | Read | Write | Create | Unlink | Purpose |
|---|---|:---:|:---:|:---:|:---:|---|
| `tally.ledger.map` | `account.group_account_user` (Accountant) | ✅ | ❌ | ❌ | ❌ | View active ledger mappings |
| `tally.ledger.map` | `account.group_account_manager` (Advisor) | ✅ | ✅ | ✅ | ✅ | Full configuration authority |
| `tally.voucher.map` | `account.group_account_user` | ✅ | ❌ | ❌ | ❌ | View document mappings |
| `tally.voucher.map` | `account.group_account_manager` | ✅ | ✅ | ✅ | ✅ | Modify voucher routing |
| `tally.uom.map` | `account.group_account_manager` | ✅ | ✅ | ✅ | ✅ | Manage unit symbols |
| `tally.sync.log` | `account.group_account_user` | ✅ | ❌ | ❌ | ❌ | Read audit logs |
| `tally.sync.log` | `account.group_account_manager` | ✅ | ✅ | ✅ | ✅ | Purge or manage audit logs |
| `tally.company` *(Multi-Company)* | `account.group_account_invoice` | ✅ | ❌ | ❌ | ❌ | View assigned company |
| `tally.company` *(Multi-Company)* | `account.group_account_manager` | ✅ | ✅ | ✅ | ✅ | Full endpoint management |

---

## 2. Network Exposure & Firewall Hardening

> ### ⚠️ CRITICAL NETWORK WARNING
> **NEVER expose Tally Prime's XML Server (Port 9000) directly to the public Internet.**  
> Tally Prime's HTTP XML Server does not natively implement TLS/HTTPS or password-based HTTP basic authentication. Exposing Port 9000 without network perimeter controls allows unauthorized parties to query or inject financial records.

### Recommended Deployment Topologies:

#### Topology A: Co-located (Highest Security)
- Odoo server and Tally Prime operate on the same physical Windows machine or internal local server.
- Server URL: `http://localhost:9000` or `http://127.0.0.1:9000`
- Zero external network exposure.

#### Topology B: Secure Private Local Area Network (LAN)
- Odoo server and Tally workstation are located on the same secure enterprise subnet (e.g. `192.168.1.0/24`).
- Windows Firewall configured to accept inbound TCP Port 9000 **only from the static IP of the Odoo server**.
  ```powershell
  # Restrict to specific Odoo server IP:
  New-NetFirewallRule -DisplayName "Tally XML Odoo Restricted" -Direction Inbound -Protocol TCP -LocalPort 9000 -RemoteAddress 192.168.1.50 -Action Allow
  ```

#### Topology C: Site-to-Site WireGuard / IPsec / Tailscale VPN
- When Odoo is cloud-hosted (e.g., AWS, DigitalOcean, Odoo.sh) and Tally is in a local office:
- Establish a secure Site-to-Site VPN or encrypted Tailscale tunnel between the cloud server and the office network.
- Odoo connects to the internal tunnel IP address (e.g., `http://100.x.y.z:9000`).

---

## 3. Data Privacy & Sensitive Payload Protection

### Audit Log Retention & Access Control
- `tally.sync.log` records the exact XML envelopes exchanged between systems to facilitate accounting audit trails.
- These logs contain partner names, invoice amounts, tax breakdowns, and addresses.
- Access to `tally.sync.log` is strictly restricted to authenticated accounting users. Public and non-accounting portal users have zero read or write access.

### Sanitization of XML Inputs
- All strings processed by `xml_builder.py` are sanitized via `_sanitize_xml_text()` to strip invalid XML 1.0 C0 control characters and null bytes (`\x00-\x08`, `\x0B-\x0C`, `\x0E-\x1F`), preventing XML injection or parser crashes.

### Safe Debugging & Release Hygiene
- In production, internal debug logging should never dump customer invoices or credentials into public or temporary filesystem paths.
- All temporary debugging files (`*.log`) must be excluded from distribution archives.
