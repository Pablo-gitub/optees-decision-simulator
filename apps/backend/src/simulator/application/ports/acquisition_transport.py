"""Application port defining acquisition transport requests, responses, and interfaces."""

from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AcquisitionArtifactRequest:
    """Provider-neutral request DTO for fetching an external data artifact.

    Contains zero provider-specific SDK, credentials, or session configuration.
    """

    uri: str
    expected_filename: str
    max_bytes: int
    allowed_content_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str) or not self.uri:
            raise ValueError("uri must be a non-empty string")
        if not isinstance(self.expected_filename, str) or not self.expected_filename:
            raise ValueError("expected_filename must be a non-empty string")
        if not isinstance(self.max_bytes, int) or self.max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        if not isinstance(self.allowed_content_types, tuple) or not self.allowed_content_types:
            raise ValueError("allowed_content_types must be a non-empty tuple of strings")
        for ct in self.allowed_content_types:
            if not isinstance(ct, str) or not ct:
                raise ValueError("each allowed content type must be a non-empty string")


@dataclass(frozen=True)
class AcquisitionArtifactResponse:
    """Immutable response DTO returned by an acquisition transport adapter.

    Encapsulates fetched byte payload, declared content type, and verified hash.
    """

    content: bytes
    content_type: str
    byte_size: int
    sha256_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, (bytes, bytearray)):
            raise TypeError("content must be bytes")
        object.__setattr__(self, "content", bytes(self.content))

        if not isinstance(self.content_type, str) or not self.content_type:
            raise ValueError("content_type must be a non-empty string")
        if not isinstance(self.byte_size, int) or self.byte_size < 0:
            raise ValueError("byte_size must be a non-negative integer")
        if len(self.content) != self.byte_size:
            raise ValueError(
                f"content length ({len(self.content)}) does not match byte_size ({self.byte_size})"
            )
        computed_sha = f"sha256:{hashlib.sha256(self.content).hexdigest()}"
        if not hmac.compare_digest(computed_sha, self.sha256_digest):
            raise ValueError("sha256_digest does not match SHA-256 of content bytes")


class AcquisitionTransportPort(ABC):
    """Port for fetching external immutable data artifacts over an isolated transport."""

    @abstractmethod
    def fetch_artifact(self, request: AcquisitionArtifactRequest) -> AcquisitionArtifactResponse:
        """Fetch a single artifact matching the request constraints.

        Raises AcquisitionTransportError on any transport, constraint, or network failure.
        """
        raise NotImplementedError
