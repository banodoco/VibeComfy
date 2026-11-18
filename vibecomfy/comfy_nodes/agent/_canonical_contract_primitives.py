"""Compatibility exports for the shared canonical contract primitives.

The implementation lives below the node-library boundary so ingest can use
it without initializing ComfyUI nodes.  Re-export the same objects to retain
one canonicalizer, one hash owner and one ContractError identity.
"""

from vibecomfy._canonical_contract_primitives import (
    ContractError,
    _JS_SAFE_INTEGER_MAX,
    _NON_CANONICAL_NUMBER,
    _compare_utf16_keys,
    _hash,
    _normalize_numeric,
    _order_json_objects_utf16,
    canonical_json,
    canonical_json_bytes_v1,
    canonicalize_contract_numeric,
    __all__,
)
