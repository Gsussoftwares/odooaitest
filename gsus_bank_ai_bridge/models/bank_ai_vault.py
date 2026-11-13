# -*- coding: utf-8 -*-
# Part of GSUS Bank AI. See LICENSE file for full copyright and licensing details.

import base64
import hashlib
import logging
from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GsusBankAiVault(models.AbstractModel):
    _name = 'gsus.bank.ai.vault'
    _description = 'GSUS Bank AI Secret Encryption & Vault Service'

    @api.model
    def _get_encryption_key(self) -> bytes:
        """Derive consistent 256-bit encryption key using database secret or system uuid."""
        ICP = self.env['ir.config_parameter'].sudo()
        secret = ICP.get_str('database.secret', '') or ICP.get_str('database.uuid', '') or 'gsus_bank_ai_master_key'
        return hashlib.sha256(secret.encode('utf-8')).digest()

    @api.model
    def encrypt_secret(self, plaintext: str) -> str:
        """Encrypt plaintext secret using XOR-hash stream encryption with base64 encoding."""
        if not plaintext:
            return ""
        try:
            key = self._get_encryption_key()
            data_bytes = plaintext.encode('utf-8')
            keystream = (key * ((len(data_bytes) // len(key)) + 1))[:len(data_bytes)]
            encrypted = bytes([b ^ k for b, k in zip(data_bytes, keystream)])
            return base64.b64encode(encrypted).decode('ascii')
        except Exception as e:
            _logger.error("Failed to encrypt bank AI secret: %s", str(e))
            raise UserError("Encryption failure in GSUS Bank AI Secret Vault.")

    @api.model
    def decrypt_secret(self, ciphertext: str) -> str:
        """Decrypt ciphertext back to plaintext."""
        if not ciphertext:
            return ""
        try:
            key = self._get_encryption_key()
            encrypted = base64.b64decode(ciphertext.encode('ascii'))
            keystream = (key * ((len(encrypted) // len(key)) + 1))[:len(encrypted)]
            decrypted = bytes([b ^ k for b, k in zip(encrypted, keystream)])
            return decrypted.decode('utf-8')
        except Exception as e:
            _logger.error("Failed to decrypt bank AI secret: %s", str(e))
            return ""

    @api.model
    def mask_secret(self, secret: str) -> str:
        """Mask a secret key for UI display."""
        if not secret:
            return ""
        cleaned = secret.strip()
        if len(cleaned) <= 8:
            return "********"
        return f"{cleaned[:5]}••••••••{cleaned[-4:]}"
