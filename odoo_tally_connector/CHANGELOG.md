# Changelog: Odoo 19 Tally Prime Connector

All notable changes to the `odoo_tally_connector` and `odoo_tally_multi_company` addons are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Odoo Semantic Versioning conventions (`19.0.MAJOR.MINOR.PATCH`).

---

## [19.0.1.0.15] - 2026-10-27

### Added
- **Odoo 19 Community & Enterprise Compatibility**: Full compliance with Odoo 19 view schemas, using modern `<list>` view architecture and responsive status badges.
- **4-Stage Smart Synchronization Engine**:
  - Stage 1: Standard Create with full inventory lines.
  - Stage 2: Automatic Alter retry when remote ID is already known to Tally.
  - Stage 3: Minimal tag retry stripping optional legacy attributes.
  - Stage 4: Minimal Journal/Accounting fallback for non-inventory vouchers.
- **E-Invoice (IRN) & E-Way Bill Integration**: Support for transmitting IRN, Acknowledgement Number & Date, and E-Way Bill details directly into Tally statutory fields.
- **TallyPrime Educational Mode Snapping**: Option to snap XML voucher dates to the 1st of the month for testing in Tally EDU without altering real Odoo accounting dates.
- **HSN Description Mapping**: Dynamic resolution of HSN descriptions from `tally.hsn.description.map`.
- **Product Category to Tally Stock Group Mapping**: Synchronize product categories directly into hierarchical Tally Stock Groups.
- **Direct UI Action Buttons**: "Sync to Tally Now", "Re-Sync (Force)", and "View Sync Logs" accessible directly from invoice and payment headers.

### Changed
- **Sign Convention Hardening**: Enhanced `_get_tally_amount()` and `_is_deemed_positive()` to ensure mathematical double-entry balance across all complex tax line combinations.
- **XML Sanitization**: Hardened `_sanitize_xml_text()` regex to strip C0 control characters, preventing XML 1.0 parser corruption.
- **Audit Logging**: Enhanced `tally.sync.log` to record complete UTF-16 Request XML, Response XML, and diagnostic error blocks.

### Fixed
- Fixed duplicate voucher creation issues caused by unreturned internal Tally GUIDs by utilizing stable `REMOTEID` tracking.
- Resolved Tally date rejection in educational installations via EDU date snapping.
- Cleaned up redundant field declarations in ledger mapping forms.

---

## [19.0.1.0.0] - 2026-10-27

### Added (Multi-Company Extension)
- **Multi-Endpoint Management**: Support for unlimited active Tally Prime connection profiles via `tally.company`.
- **Partner-to-Company Routing**: Automatic routing of invoices, bills, and payments based on partner configuration.
- **Live Connection Diagnostics**: Form and list view status indicators with real-time test connection buttons and status ribbons.
- **Batch Master Sync Pacing**: Optimized master data batch engine (30 items per payload with micro-pacing) for tunnel-safe network transmission.
- **City-to-Destination Mapping**: Automatically routes partner delivery city into Tally `BASICFINALDESTINATION`.
