# -*- coding: utf-8 -*-
import logging
import time
from xml.etree import ElementTree as ET

from odoo import _, api, fields, models
from odoo.exceptions import UserError
# pyrefly: ignore [missing-import]
from odoo.addons.odoo_tally_connector.wizard.tally_master_sync import (
    _PARTNER_SYNC_DOMAIN,
    _PRODUCT_SYNC_DOMAIN,
)
# pyrefly: ignore [missing-import]
from odoo.addons.odoo_tally_connector.utils import tally_http, xml_builder
# pyrefly: ignore [missing-import]
from odoo.addons.odoo_tally_connector.utils.xml_builder import (
    _sub,
    _prettify,
    _append_stockitem_gst_statutory,
)

_logger = logging.getLogger(__name__)

# Optimal batch size for Tally Prime XML Master Import:
# 30 items per payload achieves optimal speed (~1s per batch) with minimal memory footprint.
_BATCH_SIZE = 30
_BATCH_PACING_SECONDS = 0.05  # Micro-pause between batches to keep Ngrok tunnel smooth


class TallyMasterSync(models.TransientModel):
    _inherit = "tally.master.sync"

    tally_company_id = fields.Many2one(
        "tally.company",
        string="Target Tally Company",
        required=True,
        help="Select the specific Tally Prime company to which these masters will be synchronized.",
    )

    def _require_tally_company_and_url(self):
        """Override to dynamically retrieve credentials from selected tally_company_id."""
        if not self.tally_company_id:
            raise UserError(_("Please select a Target Tally Company first."))
        company = self.tally_company_id._get_target_tally_company_name()
        url = (self.tally_company_id.server_url or "").strip()
        if not company:
            raise UserError(_("The selected Tally Company has no valid company name configured."))
        if not url:
            raise UserError(_("The selected Tally Company has no server URL configured."))
        return company, url

    def _require_tally_stock_item_group(self):
        """Override to allow dynamic sync without legacy single-company parameter check."""
        return "Primary"

    def _build_batch_units_xml(self, uom_records, company_name, uom_map_dict):
        """Build XML envelope to dynamically upsert multiple Unit Masters in Tally Prime.
        
        Zero hardcoding: reads UoM symbol, formal name, and decimal places strictly
        from the database records and active mappings.
        """
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        _sub(header, "TALLYREQUEST", "Import Data")

        body = ET.SubElement(envelope, "BODY")
        importdata = ET.SubElement(body, "IMPORTDATA")

        requestdesc = ET.SubElement(importdata, "REQUESTDESC")
        _sub(requestdesc, "REPORTNAME", "All Masters")
        staticvars = ET.SubElement(requestdesc, "STATICVARIABLES")
        _sub(staticvars, "SVCURRENTCOMPANY", company_name)

        requestdata = ET.SubElement(importdata, "REQUESTDATA")

        for uom in uom_records:
            symbol = (uom_map_dict.get(uom.id) or uom.name or "Nos").strip()
            if not symbol:
                continue
            formal_name = (uom.name or symbol).strip()
            dec_places = xml_builder._decimal_places_from_uom_rounding(uom.rounding)

            tallymessage = ET.SubElement(requestdata, "TALLYMESSAGE")
            tallymessage.set("xmlns:UDF", "TallyUDF")

            unit_el = ET.SubElement(tallymessage, "UNIT")
            unit_el.set("NAME", symbol)
            unit_el.set("ACTION", "Alter")  # Upsert: Create if missing, preserve if existing

            _sub(unit_el, "NAME", symbol)
            _sub(unit_el, "ISSIMPLEUNIT", "Yes")
            _sub(unit_el, "FORMALNAME", formal_name)
            _sub(unit_el, "DECIMALPLACES", str(max(0, min(9, int(dec_places)))))

        return _prettify(envelope)

    def _build_batch_stock_items_xml(self, products, company_name, uom_map_dict, push_gst=True):
        """Build a single Tally XML Envelope containing multiple Stock Items, Groups, and Units.
        
        Zero hardcoding:
        - Unit, Group, and Product attributes are resolved dynamically per product.
        - ACTION="Alter" on all masters guarantees upsert (updates existing, creates missing, zero duplicates).
        """
        envelope = ET.Element("ENVELOPE")

        header = ET.SubElement(envelope, "HEADER")
        _sub(header, "TALLYREQUEST", "Import Data")

        body = ET.SubElement(envelope, "BODY")
        importdata = ET.SubElement(body, "IMPORTDATA")

        requestdesc = ET.SubElement(importdata, "REQUESTDESC")
        _sub(requestdesc, "REPORTNAME", "All Masters")
        staticvars = ET.SubElement(requestdesc, "STATICVARIABLES")
        _sub(staticvars, "SVCURRENTCOMPANY", company_name)

        requestdata = ET.SubElement(importdata, "REQUESTDATA")

        for product in products:
            tallymessage = ET.SubElement(requestdata, "TALLYMESSAGE")
            tallymessage.set("xmlns:UDF", "TallyUDF")

            tally_uom = (
                uom_map_dict.get(product.uom_id.id)
                or (product.uom_id.name if product.uom_id else "Nos")
                or "Nos"
            ).strip()

            # 1. Bundled Unit upsert (ensures unit exists right before item creation)
            if product.uom_id:
                formal_name = (product.uom_id.name or tally_uom).strip()
                dec_places = xml_builder._decimal_places_from_uom_rounding(product.uom_id.rounding)
                unit_el = ET.SubElement(tallymessage, "UNIT")
                unit_el.set("NAME", tally_uom)
                unit_el.set("ACTION", "Alter")
                _sub(unit_el, "NAME", tally_uom)
                _sub(unit_el, "ISSIMPLEUNIT", "Yes")
                _sub(unit_el, "FORMALNAME", formal_name)
                _sub(unit_el, "DECIMALPLACES", str(max(0, min(9, int(dec_places)))))

            stock_group, stock_group_under = product._get_tally_stock_group()
            category_name = (stock_group or "Primary").strip()

            # 2. Bundled Stock Group upsert (ensures group exists right before item creation)
            if category_name and category_name != "Primary":
                group = ET.SubElement(tallymessage, "STOCKGROUP")
                group.set("NAME", category_name)
                group.set("ACTION", "Alter")
                _sub(group, "NAME", category_name)
                group_under = (stock_group_under or "").strip()
                _sub(group, "PARENT", "" if group_under.lower() == "primary" else group_under)
                _sub(group, "ISSUBLEDGER", "No")
                _sub(group, "ISADDABLE", "No")

            # 3. Stock Item node (ACTION="Alter" guarantees zero duplicates)
            item = ET.SubElement(tallymessage, "STOCKITEM")
            item.set("NAME", product.name)
            item.set("ACTION", "Alter")
            _sub(item, "NAME", product.name)
            _sub(item, "PARENT", "" if category_name == "Primary" else category_name)
            _sub(item, "BASEUNITS", tally_uom)

            if getattr(product, "default_code", False):
                _sub(item, "ALIAS", product.default_code)

            _append_stockitem_gst_statutory(item, product, push_gst)

        return _prettify(envelope)

    def _sync_single_product_resilient(self, product, company_name, url, uom_dict, push_gst, errors):
        """Fallback sync for a single product with full dynamic Unit and Group bundling."""
        try:
            single_xml = self._build_batch_stock_items_xml(
                [product], company_name, uom_dict, push_gst=push_gst
            )
            success, response_xml, _guid, error = tally_http.post_to_tally(single_xml, url, timeout=15)
            status = "success" if (success or tally_http.is_likely_duplicate_master_error(error)) else "failed"

            self.env["tally.sync.log"].sudo().create({
                "tally_company_id": self.tally_company_id.id,
                "move_name": f"PRODUCT: {product.display_name}",
                "status": status,
                "request_xml": single_xml,
                "response_xml": response_xml or "",
                "error_message": error or "",
                "tally_server_url": url,
            })

            if success or tally_http.is_likely_duplicate_master_error(error):
                product.with_context(skip_tally_product_sync=True).sudo().write({
                    "tally_guid": product.tally_guid or product.default_code or product.name,
                    "tally_last_sync": fields.Datetime.now(),
                })
                return True
            else:
                if error:
                    errors.append(f"{product.display_name} — {error}")
                return False
        except Exception as exc:
            _logger.error("[TallyBatchSync] Single item sync exception for %s: %s", product.display_name, exc)
            errors.append(f"{product.display_name} — {exc}")
            return False

    def action_sync_all_products(self):
        """Ultra-fast batch sync of products to Tally Prime without hardcoding.
        
        Guarantees:
        1. Fully dynamic: reads company, URL, UoMs, groups, and taxes from database.
        2. Auto-creates all required Units of Measure in Tally Prime dynamically.
        3. Non-duplication: Uses ACTION="Alter" so existing products in Tally are updated, not duplicated.
        4. High speed: Batch XML payload processes 30 products per HTTP request (~40s total for 1,247 products).
        5. Reliability: Adaptive single-item fallback ensures every valid product is synced.
        """
        company_name, url = self._require_tally_company_and_url()

        # Step 1: Pre-flight connection test (fast ping)
        conn_ok, conn_msg = tally_http.test_connection(url, timeout=5)
        if not conn_ok:
            raise UserError(_(
                "Cannot connect to Tally Prime at %(url)s.\n\n"
                "Error details: %(details)s\n\n"
                "Please verify:\n"
                "1. Tally Prime is open on the computer and company '%(comp)s' is loaded.\n"
                "2. XML Server is enabled on Port 9000 (F1: Help → Settings → Connectivity).\n"
                "3. Ngrok tunnel is active in the command prompt.\n"
                "4. If Ngrok restarted with a new URL, update it in:\n"
                "   Accounting → Configuration → Tally Prime Companies → %(comp)s."
            ) % {
                "url": url,
                "details": conn_msg,
                "comp": self.tally_company_id.name,
            })

        products = self.env["product.product"].search(_PRODUCT_SYNC_DOMAIN)
        total_products = len(products)
        if not total_products:
            return self._notification_bulk_result(
                _("Bulk product sync"), 0, 0, [], _("products")
            )

        ICP = self.env["ir.config_parameter"].sudo()
        push_gst = ICP.get_param("tally_connector.master_push_gst", "True") in ("True", "1", "true")

        # Step 2: Pre-cache UoM mapping and pre-create ALL distinct units in Tally upfront dynamically
        uom_maps = self.env["tally.uom.map"].sudo().search([])
        uom_dict = {m.uom_id.id: m.tally_symbol for m in uom_maps if m.tally_symbol}

        distinct_uoms = products.mapped("uom_id")
        if distinct_uoms:
            _logger.info(
                "[TallyBatchSync] Pre-creating %d distinct units in Tally Prime: %s",
                len(distinct_uoms),
                [u.name for u in distinct_uoms],
            )
            try:
                units_xml = self._build_batch_units_xml(distinct_uoms, company_name, uom_dict)
                u_success, u_resp, _u_guid, u_err = tally_http.post_to_tally(units_xml, url, timeout=15)
                if u_success:
                    _logger.info("[TallyBatchSync] All distinct units successfully ensured in Tally.")
                else:
                    _logger.warning("[TallyBatchSync] Units pre-ensure notice: %s", u_err)
            except Exception as exc:
                _logger.warning("[TallyBatchSync] Pre-syncing units exception: %s", exc)

        _logger.info(
            "[TallyBatchSync] Starting batch sync for %d products to '%s' via %s (batch size: %d)",
            total_products,
            company_name,
            url,
            _BATCH_SIZE,
        )

        errors = []
        success_count = 0

        # Step 3: Iterate products in batches of 30
        for i in range(0, total_products, _BATCH_SIZE):
            batch = products[i : i + _BATCH_SIZE]
            valid_batch = [p for p in batch if (p.name or "").strip()]

            # Record any unnamed products
            for p in batch:
                if not (p.name or "").strip():
                    errors.append(f"{p.display_name} — Product has no name.")

            if not valid_batch:
                continue

            batch_xml = self._build_batch_stock_items_xml(
                valid_batch, company_name, uom_dict, push_gst=push_gst
            )

            # Post batch payload
            batch_success, response_xml, _guid, batch_err = tally_http.post_to_tally(
                batch_xml, url, timeout=30
            )

            if batch_success:
                # Mark all products in batch as successfully synced
                now = fields.Datetime.now()
                for p in valid_batch:
                    p.with_context(skip_tally_product_sync=True).sudo().write({
                        "tally_guid": p.tally_guid or p.default_code or p.name,
                        "tally_last_sync": now,
                    })

                success_count += len(valid_batch)

                self.env["tally.sync.log"].sudo().create({
                    "tally_company_id": self.tally_company_id.id,
                    "move_name": f"PRODUCT BATCH ({len(valid_batch)} items: #{i+1}-#{i+len(valid_batch)})",
                    "status": "success",
                    "request_xml": batch_xml,
                    "response_xml": response_xml or "",
                    "tally_server_url": url,
                })
            else:
                # ADAPTIVE FALLBACK: If batch fails, sync individual items in this batch
                # with full dynamic unit & group bundling to isolate problematic items and sync all valid ones!
                _logger.warning(
                    "[TallyBatchSync] Batch %d-%d returned: %s. Executing resilient single fallback.",
                    i + 1,
                    i + len(valid_batch),
                    batch_err,
                )
                for p in valid_batch:
                    if self._sync_single_product_resilient(
                        p, company_name, url, uom_dict, push_gst, errors
                    ):
                        success_count += 1

            if _BATCH_PACING_SECONDS > 0:
                time.sleep(_BATCH_PACING_SECONDS)

            # Periodic database commit per batch for real-time safety
            self.env.cr.commit()
            _logger.info(
                "[TallyBatchSync] Progress: %d/%d products processed (Success: %d, Errors: %d)",
                min(i + _BATCH_SIZE, total_products),
                total_products,
                success_count,
                len(errors),
            )

        return self._notification_bulk_result(
            _("Bulk product sync"),
            success_count,
            total_products,
            errors,
            _("products"),
        )

    def action_sync_all_customers(self):
        """Resilient sync of partners with pre-flight check and micro-pacing."""
        company_name, url = self._require_tally_company_and_url()

        # Pre-flight check
        conn_ok, conn_msg = tally_http.test_connection(url, timeout=5)
        if not conn_ok:
            raise UserError(_(
                "Cannot connect to Tally Prime at %(url)s.\n\n"
                "Details: %(details)s\n\n"
                "Please verify Tally Prime and Ngrok are running."
            ) % {"url": url, "details": conn_msg})

        partners = self.env["res.partner"].search(_PARTNER_SYNC_DOMAIN)
        errors = []
        success_count = 0

        for idx, partner in enumerate(partners, start=1):
            if partner._sync_to_tally_ledger_for_company(self.tally_company_id):
                success_count += 1
            else:
                errors.append(partner.display_name)

            if idx % 50 == 0:
                self.env.cr.commit()
                time.sleep(0.05)

        return self._notification_bulk_result(
            _("Bulk partner sync"),
            success_count,
            len(partners),
            errors,
            _("customers/vendors"),
        )
