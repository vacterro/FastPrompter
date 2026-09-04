"""Provider adapter interface for usage-limit probing.

Every provider implements the same three-method contract — discover
accounts, probe one account in isolation, report capabilities. No Qt,
no GUI state. See ``codex.py`` for a reference implementation, ``claude.py``
for the honest-unsupported fallback.
"""

from __future__ import annotations

import abc

from fastprompter.core.usage_limits.model import AccountRef, UsageSnapshot


class UsageProvider(abc.ABC):
    """Abstract provider for one AI tool (Codex, Claude, …)."""

    @property
    @abc.abstractmethod
    def provider_id(self) -> str:
        ...

    @abc.abstractmethod
    def discover_accounts(self) -> list[AccountRef]:
        """Return every discoverable account for this provider.

        Must be quick (no subprocess spawning), cache-friendly, and safe to
        call from the main thread. Returns an empty list when the provider
        tool is not installed.
        """
        ...

    @abc.abstractmethod
    def probe(self, account: AccountRef, deadline: float) -> UsageSnapshot:
        """Fetch the current usage snapshot for one account.

        ``deadline`` is ``time.monotonic()`` absolute -- the implementation
        must return (with status OK or ERROR) before it expires. It MUST NOT
        block longer than ``deadline``, even if that means aborting the probe
        and returning an ERROR/STALE snapshot.

        Never raises; any exception is caught by the service and converted to
        an ERROR snapshot.
        """
        ...

    def shutdown(self) -> None:
        """Release any provider-level resources."""
