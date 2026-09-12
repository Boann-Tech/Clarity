"""Shared test isolation for process-wide API state."""

import pytest


@pytest.fixture(autouse=True)
def _reset_api_state():
    from app import main

    main._rate_limiter.reset()
    main._response_cache.clear()
    yield
    main._rate_limiter.reset()
    main._response_cache.clear()