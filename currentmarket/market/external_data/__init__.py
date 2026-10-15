"""Provider-independent external real-estate integration framework.

No provider is configured. Importing this package does not open a network
connection or a database connection.
"""

from external_data.adapter import (
    SCHEMA_NOT_CONFIRMED_MESSAGE,
    AdaptedRecords,
    MappedProviderAdapter,
    ProviderFieldMap,
    UnconfirmedProviderAdapter,
    adapt_provider_payload,
)
from external_data.client import ExternalRealEstateAPIClient
from external_data.config import (
    NOT_CONFIGURED_MESSAGE,
    PROVIDER_NOT_CONFIGURED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    ExternalAPIConfig,
    load_config,
)
from external_data.ingestion import ExistingProject, ExternalDataIngestion, decide_write, prepare_record
from external_data.mapper import map_record, schema_support_report
from external_data.models import (
    MarketData,
    ProjectData,
    ProvenanceData,
    RentData,
    StandardRecord,
)
from external_data.normalizer import CANONICAL_MICRO_MARKETS, resolve_micro_market
from external_data.storage import StorageResult, ensure_external_schema, store_external_record

__all__ = [
    "SCHEMA_NOT_CONFIRMED_MESSAGE",
    "CANONICAL_MICRO_MARKETS",
    "AdaptedRecords",
    "MappedProviderAdapter",
    "ProviderFieldMap",
    "UnconfirmedProviderAdapter",
    "adapt_provider_payload",
    "NOT_CONFIGURED_MESSAGE",
    "PROVIDER_NOT_CONFIGURED_MESSAGE",
    "UNAVAILABLE_MESSAGE",
    "ExistingProject",
    "ExternalAPIConfig",
    "ExternalDataIngestion",
    "ExternalRealEstateAPIClient",
    "MarketData",
    "ProjectData",
    "ProvenanceData",
    "RentData",
    "StandardRecord",
    "decide_write",
    "load_config",
    "map_record",
    "StorageResult",
    "ensure_external_schema",
    "prepare_record",
    "resolve_micro_market",
    "schema_support_report",
    "store_external_record",
]
