"""Adversarial-variant construction pipeline.

Builds 'unanswerable' variants of data-analysis benchmark tasks by removing the
answer-critical signal, then validates (via a mandatory gate) that the signal is
truly absent and not recoverable from any in-file substitute. A variant that
cannot pass the gate is never emitted.

Public API:
    from benchmarks.variant_pipeline import VariantSpec, build_variant, validate, UnsupportedFormat
"""
from .spec import VariantSpec, Op, SignalCheck
from .adapters import get_adapter, UnsupportedFormat
from .validator import validate, CheckResult
from .builder import build_variant, BuildResult

__all__ = [
    "VariantSpec", "Op", "SignalCheck",
    "get_adapter", "UnsupportedFormat",
    "validate", "CheckResult",
    "build_variant", "BuildResult",
]
