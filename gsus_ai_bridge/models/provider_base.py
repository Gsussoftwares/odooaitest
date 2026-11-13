# -*- coding: utf-8 -*-
# Part of GSUS AI. See LICENSE file for full copyright and licensing details.

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

_logger = logging.getLogger(__name__)


class ProviderResponse:
    """Standardized response from any AI provider."""
    def __init__(
        self,
        content: str = "",
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        raw_response: Optional[Dict[str, Any]] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        error: Optional[str] = None,
        model: str = "",
        duration_ms: float = 0.0,
    ):
        self.content = content or ""
        self.tool_calls = tool_calls or []
        self.raw_response = raw_response or {}
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens or (prompt_tokens + completion_tokens)
        self.error = error
        self.model = model
        self.duration_ms = duration_ms

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_success(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'content': self.content,
            'tool_calls': self.tool_calls,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'error': self.error,
            'model': self.model,
            'duration_ms': self.duration_ms,
        }


class BaseAIProvider(ABC):
    """Abstract base contract for AI model providers."""

    def __init__(self, provider_record):
        self.provider = provider_record
        self.env = provider_record.env

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Return provider capabilities (tools, streaming, vision, json_mode)."""
        pass

    @abstractmethod
    def validate_configuration(self) -> List[str]:
        """Validate provider settings and credentials. Return list of error messages."""
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Test connection to provider endpoint. Return status and diagnostics."""
        pass

    @abstractmethod
    def generate_response(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ProviderResponse:
        """Send chat messages and return standardized ProviderResponse."""
        pass

    @abstractmethod
    def format_tools(self, tools: List[Dict[str, Any]]) -> Any:
        """Convert standard tool schemas into provider-specific tool schemas."""
        pass

    @abstractmethod
    def parse_tool_calls(self, raw_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract tool calls from provider raw response."""
        pass
