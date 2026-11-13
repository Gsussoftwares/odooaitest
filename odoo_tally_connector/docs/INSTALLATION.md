# Installation Guide: Odoo 19 Tally Prime Connector

This guide provides clean, production-verified instructions for installing the **Tally Prime Connector** (`odoo_tally_connector`) and the optional **Tally Multi-Company Extension** (`odoo_tally_multi_company`) on **Odoo 19 Community Edition** and **Odoo 19 Enterprise Edition**.

---

## 1. Environment Preparation

### Step 1: Verify Python Environment & Dependencies
The connector requires the standard Python `requests` library for HTTP XML communication with Tally Prime.

#### For Linux / Ubuntu Server:
```bash
# Activate your Odoo 19 virtual environment
source /opt/odoo/odoo-venv/bin/activate

# Install requests if not already installed
pip install requests

# Verify installation
python -c "import requests; print('requests version:', requests.__version__)"
```

#### For Windows Server:
```powershell
# Open PowerShell and activate your Odoo Python environment
cd C:\odoo\server
.\venv\Scripts\activate

# Install requests
pip install requests

# Verify installation
python -c "import requests; print('requests version:', requests.__version__)"
```

---

## 2. Deploying Addons to Odoo

### Step 2: Add Addons to Odoo Addons Path
Place the addon directories into your configured custom addons directory:

- Base Connector: `custom_addon/odoo_tally_connector`
- Multi-Company Extension (Optional): `custom_addon/odoo_tally_multi_company`

Ensure that your `odoo.conf` file includes the path to `custom_addon` in the `addons_path` setting:

#### Example `odoo.conf`:
```ini
[options]
addons_path = /opt/odoo/odoo/addons,/opt/odoo/custom_addons
```

*(On Windows, use standard path format: `addons_path = C:\odoo\server\odoo\addons,C:\odoo\server\custom_addon`)*

### Step 3: Restart Odoo Service
Apply configuration changes by restarting your Odoo service:

#### Linux:
```bash
sudo systemctl restart odoo
```

#### Windows:
```powershell
Restart-Service odoo-server
# Or restart your development server process
```

---

## 3. Module Installation via Odoo UI

### Step 4: Update Apps List
1. Log into your Odoo 19 instance with an Administrator account.
2. Enable Developer Mode (**Settings → General Settings → Activate Developer Mode**).
3. Navigate to the **Apps** menu.
4. In the top navigation bar, click **Update Apps List**.
5. In the confirmation dialog, click **Update**.

### Step 5: Install Base Module (`odoo_tally_connector`)
1. In the **Apps** search bar, remove the default "Apps" filter.
2. Search for `Tally Prime Connector`.
3. Locate the card titled **Tally Prime Connector** (`odoo_tally_connector`).
4. Click **Install**.
5. Wait for the page to refresh upon successful completion.

### Step 6: Install Multi-Company Extension (`odoo_tally_multi_company`) *(Optional)*
> **Note**: `odoo_tally_multi_company` depends on `odoo_tally_connector`. Always install the base connector first or install both together.
1. Search for `Tally Multi-Company Connector`.
2. Locate the card titled **Tally Multi-Company Connector** (`odoo_tally_multi_company`).
3. Click **Install**.

---

## 4. Command-Line Installation (Alternative for Automated Deployments)

For automated staging, CI/CD, or headless server installations:

```bash
# Linux
odoo-bin -c /etc/odoo.conf -d <database_name> -i odoo_tally_connector,odoo_tally_multi_company --stop-after-init

# Windows
.\venv\Scripts\python.exe odoo-bin -c odoo.conf -d <database_name> -i odoo_tally_connector,odoo_tally_multi_company --stop-after-init
```

---

## 5. Post-Installation Verification Checklist

After installation, verify that the following views and models are properly registered:

- [ ] **Menu Presence**: Navigate to **Invoicing (or Accounting) → Customers → Tally Connector**. Confirm the menu structure exists:
  - `Sync Logs`
  - `E-Invoice / E-Way Bill Logs`
  - `Mappings` (`Ledger Mapping`, `Voucher Type Mapping`, `UoM Mapping`, `Product Category Mapping`, `HSN Description Mapping`)
  - `Bulk Master Sync`
  - `Tally Companies` *(if multi-company extension is installed)*
- [ ] **Invoice View Integration**: Open any Customer Invoice (**Invoicing → Customers → Invoices**). Confirm the **Tally Integration** (or **Tally Sync**) tab is present on the form.
- [ ] **Settings Section**: Navigate to **Accounting → Settings → Tally Prime Connector** (or **Invoicing → Settings**). Confirm settings fields are visible.
- [ ] **Default Seed Data**: Navigate to **Customers → Tally Connector → Mappings → Voucher Type Mapping**. Confirm default voucher types (`Sales`, `Purchase`, `Credit Note`, `Debit Note`, `Receipt`, `Payment`) are pre-populated.

---

## 6. Upgrading the Modules

When deploying newer versions of the connector:

1. Replace the files in your `custom_addon/odoo_tally_connector` folder.
2. Restart the Odoo service.
3. Run the module upgrade:
   - **Via UI**: Go to **Apps**, search for `Tally Prime Connector`, and click **Upgrade**.
   - **Via CLI**:
     ```bash
     odoo-bin -c odoo.conf -d <database_name> -u odoo_tally_connector,odoo_tally_multi_company --stop-after-init
     ```

---

## 7. Safe Uninstall Considerations

If you ever need to uninstall the connector:

1. **Transaction Integrity**: Uninstalling the module removes synchronization logs and mapping tables from Odoo. It **never modifies or deletes transactions already posted in Tally Prime**.
2. **Dependent Extensions**: If `odoo_tally_multi_company` is installed, uninstall it **before** uninstalling `odoo_tally_connector`.
3. **Database Safeguard**: Take a database backup before performing any module uninstall:
   ```bash
   pg_dump -h localhost -p 5433 -U odoo -d <database_name> -F c -b -v -f odoo_backup_before_uninstall.dump
   ```
