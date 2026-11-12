"""LangSmith and OpenTelemetry tracing utilities for the Transaction Fraud Scorer (PRD-018)."""

import functools
import inspect
import logging
import os
import random
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import UUID, uuid4

from fraud_scorer.config import Settings, settings
from fraud_scorer.observability.sanitizer import sanitize_transaction_payload

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

_CACHED_CLIENT: Any = None
_CACHED_KEY: tuple[str, str] | None = None


def sync_langsmith_env(current_settings: Settings | None = None) -> bool:
    """Synchronize LangSmith environment variables with application settings.

    Returns True if LangSmith tracing is active, or False if disabled.
    """
    cfg = current_settings or settings
    if cfg.is_langsmith_enabled():
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_ENDPOINT"] = cfg.langsmith_endpoint
        os.environ["LANGSMITH_PROJECT"] = cfg.langsmith_project
        if cfg.langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = cfg.langsmith_api_key
        return True

    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return False


def get_langsmith_client(current_settings: Settings | None = None) -> Any | None:
    """Return a configured langsmith.Client when tracing is enabled, or None when disabled."""
    global _CACHED_CLIENT, _CACHED_KEY
    cfg = current_settings or settings
    if not sync_langsmith_env(cfg):
        return None

    api_key = (cfg.langsmith_api_key or "").strip()
    endpoint = cfg.langsmith_endpoint.strip()
    cache_key = (endpoint, api_key)

    if _CACHED_CLIENT is not None and _CACHED_KEY == cache_key:
        return _CACHED_CLIENT

    try:
        from langsmith import Client

        _CACHED_CLIENT = Client(
            api_url=endpoint,
            api_key=api_key,
        )
        _CACHED_KEY = cache_key
        return _CACHED_CLIENT
    except Exception as exc:
        logger.warning("Failed to initialize LangSmith client: %s", exc)
        return None


# Alias per PRD-018 package exports
get_tracer = get_langsmith_client


def build_langchain_run_config(
    tx_id: str,
    account_id: str,
    policy_year: str = "2026",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    run_id: str | UUID | None = None,
    run_name: str = "FraudEvaluationSupervisor",
    current_settings: Settings | None = None,
) -> dict[str, Any]:
    """Construct a LangChain/LangGraph RunnableConfig with sanitized metadata and correlation run_id."""
    cfg = current_settings or settings
    sync_langsmith_env(cfg)

    resolved_uuid = UUID(str(run_id)) if run_id is not None else uuid4()
    base_tags = [
        "fraud-scorer",
        f"env:{cfg.environment}",
        f"policy_year:{policy_year}",
        f"provider:{cfg.default_llm_provider}",
    ]
    if tags:
        for t in tags:
            if t not in base_tags:
                base_tags.append(t)

    raw_meta: dict[str, Any] = {
        "transaction_id": tx_id,
        "account_id": account_id,
        "policy_year": policy_year,
        "langsmith_project": cfg.langsmith_project,
        "langsmith_enabled": cfg.is_langsmith_enabled(),
    }
    if metadata:
        raw_meta.update(metadata)

    clean_meta = sanitize_transaction_payload(raw_meta) if cfg.langsmith_mask_pii else raw_meta

    return {
        "run_name": run_name,
        "run_id": resolved_uuid,
        "tags": base_tags,
        "metadata": clean_meta,
    }


# Alias per PRD-018 package exports
create_trace_config = build_langchain_run_config


def safe_traceable(
    name: str | None = None,
    run_type: str = "chain",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Decorator wrapping langsmith.traceable that acts as a zero-overhead no-op when disabled."""

    def _decorator(func: F) -> F:
        try:
            from langsmith.run_helpers import traceable

            traced_fn = traceable(
                name=name or func.__name__,
                run_type=run_type,  # type: ignore[arg-type]
                tags=tags,
                metadata=metadata,
                process_inputs=(
                    sanitize_transaction_payload if settings.langsmith_mask_pii else None
                ),
            )(func)
        except Exception:
            traced_fn = func

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not settings.is_langsmith_enabled():
                    return await func(*args, **kwargs)
                if settings.langsmith_sample_rate < 1.0 and random.random() > settings.langsmith_sample_rate:
                    return await func(*args, **kwargs)
                return await traced_fn(*args, **kwargs)

            return _async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not settings.is_langsmith_enabled():
                return func(*args, **kwargs)
            if settings.langsmith_sample_rate < 1.0 and random.random() > settings.langsmith_sample_rate:
                return func(*args, **kwargs)
            return traced_fn(*args, **kwargs)

        return _sync_wrapper  # type: ignore[return-value]

    return _decorator


def record_feedback(
    run_id: str | UUID | None,
    key: str = "analyst_decision",
    score: float = 1.0,
    comment: str | None = None,
    current_settings: Settings | None = None,
) -> bool:
    """Submit human analyst feedback to LangSmith for a completed transaction run_id.

    Gracefully returns False without raising if LangSmith is disabled or unreachable.
    """
    if not run_id:
        return False

    cfg = current_settings or settings
    client = get_langsmith_client(cfg)
    if client is None:
        return False

    try:
        clean_comment = mask_pan_if_needed(comment, cfg.langsmith_mask_pii) if comment else None
        client.create_feedback(
            run_id=str(run_id),
            key=key,
            score=score,
            comment=clean_comment,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to record LangSmith feedback for run_id=%s: %s", run_id, exc)
        return False


def mask_pan_if_needed(text: str, mask_enabled: bool = True) -> str:
    """Mask PAN patterns in free-text comments when PII masking is enabled."""
    if not mask_enabled:
        return text
    from fraud_scorer.observability.sanitizer import mask_pan

    return mask_pan(text)


# Alias per PRD-018 package exports
record_analyst_feedback = record_feedback


def get_langsmith_trace_url(
    run_id: str | None,
    current_settings: Settings | None = None,
) -> str | None:
    """Return a shareable/navigable LangSmith run URL for the given run_id."""
    if not run_id:
        return None
    cfg = current_settings or settings
    base = cfg.langsmith_endpoint.rstrip("/")
    if "api.smith.langchain.com" in base:
        ui_base = "https://smith.langchain.com"
    else:
        ui_base = base
    return f"{ui_base}/r/{run_id}"
