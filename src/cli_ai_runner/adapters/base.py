from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class InvocationSpec:
    argv: list[str]
    env_overrides: dict[str, str]

class AgentAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """The identifier of the agent."""

    @abstractmethod
    def resolve_cmd(self) -> list[str] | None:
        """Return resolved argv prefix or None if not found."""

    @abstractmethod
    def build_invocation(self, prompt: str, resolved_cmd: list[str]) -> InvocationSpec:
        """Build full subprocess invocation for one prompt."""

    @abstractmethod
    def is_installed(self) -> bool:
        """Fast check to see if the agent is installed."""

    @abstractmethod
    def install(self, dry_run: bool = False) -> bool:
        """Execute or print the install command. Returns True on success."""

    def post_install_verify(self) -> bool:
        """Re-run is_installed() after install."""
        return self.is_installed()
