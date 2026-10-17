"""The evaluation harnesses: measurement tools run against the Golden Set.

Kept outside the core package (`edgar_rag`), like `edgar_answer`, because Arms and
judges still to come need third-party packages (embeddings, a cross-encoder, provider
SDKs) that the core package must not import (ADR 0006).
"""
