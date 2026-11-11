"""Base Adapter interface for VidyutSetu Vendor Systems."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple
from backend.models.canonical import CanonicalPayload, DiagnosticIssue
from backend.models.vendor import VendorProfile


class BaseAdapter(ABC):
    """Abstract base adapter for converting between vendor raw payloads and Canonical Data Model."""

    def __init__(self, profile: VendorProfile):
        self.profile = profile

    @abstractmethod
    def parse_to_canonical(self, raw_data: Any) -> Tuple[CanonicalPayload, List[DiagnosticIssue]]:
        """Parse raw vendor format (JSON string, dict, or CSV text) into CanonicalPayload.
        Returns:
            Tuple of (CanonicalPayload, List[DiagnosticIssue])
        """
        pass

    @abstractmethod
    def serialize_from_canonical(self, canonical: CanonicalPayload) -> Any:
        """Serialize a CanonicalPayload into vendor-specific format (dict, JSON string, or CSV text)."""
        pass
