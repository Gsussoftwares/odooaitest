# -*- coding: utf-8 -*-
"""
utils/tally_http.py

HTTP transmission layer for the Odoo Tally Prime Connector.

Handles all communication with the Tally Prime XML HTTP server
running on the local Windows machine (default: http://localhost:9000).

Using the `requests` library for robust HTTP handling with timeout support.
"""

import json
import logging
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

_logger = logging.getLogger(__name__)
_logger.info(
    "[odoo_tally_connector] tally_http loaded (build marker: sv-yyyymmdd-envelope, POST log includes SVFROMDATE flags)"
)

def _agent_debug_log(message, data, hypothesis_id, location, run_id="pre"):
    """No-op in production release to protect data privacy and disk space."""
    pass

_DEFAULT_TIMEOUT = 10  # seconds
_TALLY_CONTENT_TYPE = "text/xml;charset=utf-16"
_TALLY_HEADERS = {
    "Content-Type": _TALLY_CONTENT_TYPE,
}


# ---------------------------------------------------------------------------
# Core POST function
# ---------------------------------------------------------------------------


def post_to_tally(xml_string, url, timeout=_DEFAULT_TIMEOUT):
    """
    POST an XML string to the Tally Prime HTTP XML server.

    Tally Prime listens on Port 9000 (configurable in Tally Gateway settings).
    It accepts UTF-16 encoded XML and responds with an XML result.

    Args:
        xml_string (str): The complete XML envelope to send.
        url (str): Tally server URL (e.g., 'http://localhost:9000').
        timeout (int): Request timeout in seconds. Default: 10.

    Returns:
        tuple: (success: bool, response_text: str, tally_guid: str, error: str)
            - success: True if Tally accepted the import without errors.
            - response_text: Raw XML response from Tally.
            - tally_guid: GUID extracted from the response (empty if not found).
            - error: Error message string (empty if success).
    """
    if not REQUESTS_AVAILABLE:
        return (
            False,
            "",
            "",
            'The "requests" Python library is not installed. Run: pip install requests',
        )

    if not url:
        return False, "", "", "Tally server URL is not configured."

    try:
        _logger.info(
            "[TallyHTTP] POST to %s — %d chars | SVFROMDATE=%s SVTODATE=%s <DATE>=%s",
            url,
            len(xml_string),
            "SVFROMDATE" in xml_string,
            "SVTODATE" in xml_string,
            "<DATE>" in xml_string,
        )
        _logger.warning(
            "[TallyHTTP] sync payload check xml_chars=%s has_SVFROMDATE=%s has_SVTODATE=%s",
            len(xml_string),
            "SVFROMDATE" in xml_string,
            "SVTODATE" in xml_string,
        )

        # Tally requires the data encoded as UTF-16 (Little Endian BOM)
        encoded_data = xml_string.encode("utf-16")
        # region agent log
        _i = xml_string.find("<DATE>")
        _agent_debug_log(
            "post_to_tally before HTTP",
            {
                "url": url,
                "xml_chars": len(xml_string),
                "encoded_bytes": len(encoded_data),
                "utf16_bom_hex": encoded_data[:4].hex()
                if len(encoded_data) >= 4
                else "",
                "has_DATE_open": "<DATE>" in xml_string,
                "date_snippet": xml_string[_i : _i + 48] if _i >= 0 else "",
            },
            "H2",
            "tally_http.py:post_to_tally",
        )
        # endregion

        response = requests.post(
            url.rstrip("/"),
            data=encoded_data,
            headers=_TALLY_HEADERS,
            timeout=timeout,
        )
        response.raise_for_status()

        response_text = _safe_decode_response(response)
        _logger.debug("[TallyHTTP] Response: %s", response_text[:500])

        success, guid, error_msg = _parse_tally_response(response_text)
        return success, response_text, guid, error_msg

    except requests.exceptions.ConnectionError:
        msg = (
            f"Cannot connect to Tally at {url}. "
            "Verify Tally Prime is running and the XML Server is enabled on Port 9000."
        )
        _logger.warning("[TallyHTTP] Connection error: %s", msg)
        return False, "", "", msg

    except requests.exceptions.Timeout:
        msg = f"Request to Tally timed out after {timeout} seconds."
        _logger.warning("[TallyHTTP] Timeout: %s", msg)
        return False, "", "", msg

    except requests.exceptions.HTTPError as exc:
        msg = f"HTTP error from Tally: {exc}"
        _logger.error("[TallyHTTP] HTTP error: %s", msg)
        return False, str(exc), "", msg

    except Exception as exc:  # noqa: BLE001
        msg = f"Unexpected error during Tally sync: {exc}"
        _logger.exception("[TallyHTTP] Unexpected error")
        return False, "", "", msg


# ---------------------------------------------------------------------------
# Connection test
# ---------------------------------------------------------------------------


def test_connection(url, timeout=5):
    """
    Test connectivity with the Tally server.

    Sends a minimal export request and expects a valid XML response.

    Args:
        url (str): Tally server URL.
        timeout (int): Timeout in seconds.

    Returns:
        tuple: (success: bool, message: str)
    """
    if not REQUESTS_AVAILABLE:
        return False, 'The "requests" library is not installed (pip install requests).'

    if not url:
        return False, "Tally server URL is empty. Please configure it in Settings."

    try:
        # Minimal export request — does not require a specific company name
        test_xml = (
            '<?xml version="1.0" encoding="utf-16"?>'
            "<ENVELOPE>"
            "<HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER>"
            "<BODY><EXPORTDATA><REQUESTDESC>"
            "<REPORTNAME>List of Companies</REPORTNAME>"
            "</REQUESTDESC></EXPORTDATA></BODY>"
            "</ENVELOPE>"
        )

        encoded = test_xml.encode("utf-16")
        response = requests.post(
            url.rstrip("/"),
            data=encoded,
            headers=_TALLY_HEADERS,
            timeout=timeout,
        )

        if response.status_code == 200:
            text = _safe_decode_response(response)
            if "<ENVELOPE>" in text or "<BODY>" in text:
                return True, "Connected to Tally Prime successfully."
            return (
                True,
                "Tally responded (response may not be XML, but server is reachable).",
            )

        return False, f"Tally returned HTTP {response.status_code}."

    except requests.exceptions.ConnectionError:
        return False, (
            f"Could not connect to {url}. "
            "Make sure Tally Prime is open and the XML Server is enabled."
        )
    except requests.exceptions.Timeout:
        return False, f"Connection to {url} timed out after {timeout} seconds."
    except Exception as exc:  # noqa: BLE001
        return False, f"Error: {exc}"


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def is_likely_duplicate_master_error(message):
    """
    Heuristic: Tally rejected a Create because the master already exists.

    Used to treat “already exists” responses as success when ensuring units/ledgers.
    """
    if not message or not str(message).strip():
        return False
    low = str(message).lower()
    if "already" in low and "exist" in low:
        return True
    if "duplicate" in low:
        return True
    return False


def voucher_import_retry_as_alter(response_text):
    """
    Detect Tally responses where Create likely failed because the voucher already exists:
    EXCEPTIONS>0 but no LINEERROR text and no CREATED/ALTERED counts — common for duplicate
    REMOTEID/VOUCHERNUMBER when Odoo has no tally_guid yet.
    """
    if not (response_text or "").strip():
        return False
    try:
        root = ET.fromstring(response_text.strip())
    except ET.ParseError:
        return False
    for el in root.findall(".//LINEERROR"):
        if (el.text or "").strip():
            return False

    exc_el = root.find(".//EXCEPTIONS")
    exc_n = 0
    if exc_el is not None and exc_el.text:
        try:
            exc_n = int(exc_el.text.strip())
        except ValueError:
            exc_n = 0
    if exc_n < 1:
        return False

    def _int(tag):
        el = root.find(f".//{tag}")
        if el is None or not el.text:
            return 0
        try:
            return int(el.text.strip())
        except ValueError:
            return 0

    if _int("CREATED") > 0 or _int("ALTERED") > 0:
        return False
    return True


def _parse_tally_response(response_text):
    """
    Parse Tally's XML response to determine success/failure and extract the GUID.

    Tally returns XML with tags like:
        <RESPONSE>
            <LINEERROR>...</LINEERROR>   ← indicates a failure
            <CREATED>1</CREATED>         ← number of records created
            <ALTERED>0</ALTERED>
        </RESPONSE>

    Args:
        response_text (str): Raw XML string from Tally.

    Returns:
        tuple: (success: bool, guid: str, error_message: str)
    """
    if not response_text or not response_text.strip():
        return False, "", "Tally returned an empty response."

    try:
        root = ET.fromstring(response_text.strip())
        # region agent log
        _nodes = []
        for el in root.iter():
            t = (el.text or "").strip()
            if t:
                _nodes.append({"tag": el.tag, "text": t[:300]})
        _exc_probe = root.find(".//EXCEPTIONS")
        _agent_debug_log(
            "parse_tally_response parsed",
            {
                "root_tag": root.tag,
                "response_len": len(response_text),
                "response_full": response_text[:4000],
                "EXCEPTIONS_text": (_exc_probe.text or "").strip()
                if _exc_probe is not None
                else "",
                "nonempty_nodes": _nodes[:60],
            },
            "H3",
            "tally_http.py:_parse_tally_response",
        )
        # endregion
    except ET.ParseError as exc:
        _logger.warning("[TallyHTTP] Could not parse Tally response XML: %s", exc)
        # Non-XML but 200 OK — might still have worked
        if "Created" in response_text or "CREATED" in response_text:
            return True, "", ""
        return False, "", f"Could not parse Tally response: {exc}"

    # LINEERROR means import failed (Tally sometimes sets ERRORS=0 but EXCEPTIONS=1)
    line_errors = root.findall(".//LINEERROR")
    if line_errors:
        errors = " | ".join(
            (e.text or "").strip() for e in line_errors if (e.text or "").strip()
        )
        if errors:
            msg = f"Tally import error: {errors}"
            if "voucher date is missing" in errors.lower():
                msg += (
                    " — Odoo sent a <DATE> tag; TallyPrime often still shows this when the date is "
                    "not allowed (e.g. TallyPrime EDU only permits the 1st, 2nd and last day of "
                    "each month), the accounting period is closed, or Books Beginning is after the "
                    "voucher date. Retry with invoice date on 1st/last of month or use a licensed "
                    "Tally company and open the period."
                )
            return False, "", msg

    # EXCEPTIONS > 0: failure even when LINEERROR is absent (Tally still returns ERRORS=0)
    exc_el = root.find(".//EXCEPTIONS")
    exc_n = 0
    if exc_el is not None and exc_el.text:
        try:
            exc_n = int(exc_el.text.strip())
        except ValueError:
            exc_n = 0
    if exc_n > 0:
        # Collect all non-empty tags from the response for transparency
        raw_tags = []
        for el in root.iter():
            txt = (el.text or "").strip()
            if txt and el.tag not in (
                "CREATED",
                "ALTERED",
                "DELETED",
                "ERRORS",
                "EXCEPTIONS",
                "LASTVCHID",
                "LASTMID",
                "COMBINED",
                "IGNORED",
                "CANCELLED",
            ):
                raw_tags.append(f"{el.tag}: {txt}")

        raw_evidence = (
            "\n".join(raw_tags) if raw_tags else "No specific error tags found."
        )

        return (
            False,
            "",
            (
                f"Tally reported import exceptions (EXCEPTIONS={exc_n}).\n\n"
                f"--- RAW TALLY RESPONSE TAGS ---\n{raw_evidence}\n"
                "-------------------------------\n\n"
                "Typical causes for empty error messages: \n"
                "- Duplicate VOUCHERNUMBER/REMOTEID\n"
                "- Multiple BILLALLOCATIONS with the same New Ref name on one voucher\n"
                "- Ledger / voucher type mismatch (LEDGERNAME or VOUCHERTYPENAME not in Tally)\n"
                "- Tally company period (Alt+F2) is closed or mismatch\n"
                "- TallyPrime EDU date limits (only 1st, 2nd, last day allowed)"
            ),
        )

    # Check CREATED count
    created_el = root.find(".//CREATED")
    if created_el is not None and created_el.text:
        try:
            created_count = int(created_el.text.strip())
            if created_count > 0:
                # Try to extract GUID from response
                guid = _extract_guid(root)
                return True, guid, ""
        except ValueError:
            pass

    # Master / voucher updates often report ALTERED instead of CREATED
    altered_el = root.find(".//ALTERED")
    if altered_el is not None and altered_el.text:
        try:
            altered_count = int(altered_el.text.strip())
            if altered_count > 0:
                guid = _extract_guid(root)
                return True, guid, ""
        except ValueError:
            pass

    # ERRORS is usually a *count* — only treat as failure when > 0 (not "0", which is success)
    err_el = root.find(".//ERROR")
    if err_el is not None and (err_el.text or "").strip():
        return False, "", f"Tally error: {err_el.text.strip()}"

    errors_count_el = root.find(".//ERRORS")
    if errors_count_el is not None and errors_count_el.text:
        try:
            err_count = int(errors_count_el.text.strip())
            if err_count > 0:
                return False, "", f"Tally reported {err_count} error(s)."
        except ValueError:
            txt = errors_count_el.text.strip()
            if txt:
                return False, "", f"Tally error: {txt}"

    err_msg_el = root.find(".//ERRORMESSAGE")
    if err_msg_el is not None and (err_msg_el.text or "").strip():
        return False, "", f"Tally error: {err_msg_el.text.strip()}"

    # Ambiguous: no errors, no created/altered count — treat as failure
    # Tally may have received it but failed to process it (check Tally Exception Reports)
    _logger.warning(
        "[TallyHTTP] Ambiguous Tally response — no CREATED or LINEERROR found."
    )
    return (
        False,
        "",
        "Tally did not confirm record creation. Check “Exception Reports” in Tally (Gateway > Display > Exception Reports).",
    )


def _extract_guid(root):
    """
    Attempt to extract a voucher/master identifier from Tally's response XML.

    Tally import responses often return LASTVCHID (numeric) instead of GUID.
    """
    for tag in ("GUID", "REMOTEID", "MASTERID"):
        el = root.find(f".//{tag}")
        if el is not None and el.text:
            return el.text.strip()
    last_vch = root.find(".//LASTVCHID")
    if last_vch is not None and (last_vch.text or "").strip():
        return last_vch.text.strip()
    return ""


def _safe_decode_response(response):
    """
    Safely decode a requests.Response body, trying UTF-16 first then UTF-8.

    Tally often responds in UTF-16 encoding to match the request type.

    Args:
        response (requests.Response): The HTTP response object.

    Returns:
        str: Decoded response text.
    """
    try:
        return response.content.decode("utf-16")
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        return response.content.decode("utf-8")
    except UnicodeDecodeError:
        return response.text  # requests default fallback
