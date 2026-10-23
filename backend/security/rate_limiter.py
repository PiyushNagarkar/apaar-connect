"""
In-memory sliding window rate limiter for login protection.
"""
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from backend.schemas.errors import AppException

MAX_ATTEMPTS = 5
WINDOW_SECONDS = 60


class LoginRateLimiter:
    def __init__(self, max_attempts: int = MAX_ATTEMPTS, window_seconds: int = WINDOW_SECONDS):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        # key -> list of failure timestamps
        self.attempts: Dict[str, List[float]] = defaultdict(list)

    def _cleanup(self, key: str, now: float):
        cutoff = now - self.window_seconds
        self.attempts[key] = [t for t in self.attempts[key] if t > cutoff]

    def check(self, key: str):
        """Raises HTTP 429 if rate limit is exceeded."""
        now = time.time()
        self._cleanup(key, now)
        if len(self.attempts[key]) >= self.max_attempts:
            oldest = self.attempts[key][0]
            retry_after = int(self.window_seconds - (now - oldest)) + 1
            raise AppException(
                code="RATE_LIMIT_EXCEEDED",
                message=f"Too many failed login attempts. Try again in {retry_after} seconds.",
                status_code=429,
                details={"retry_after_seconds": retry_after},
            )

    def record_failure(self, key: str):
        now = time.time()
        self._cleanup(key, now)
        self.attempts[key].append(now)

    def reset(self, key: str):
        if key in self.attempts:
            del self.attempts[key]


# Global rate limiter instance
login_rate_limiter = LoginRateLimiter()
