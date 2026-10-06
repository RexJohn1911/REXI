"""Version and environment metadata for REXI Research Engine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchVersion:
    major: int = 0
    minor: int = 1
    patch: int = 0
    suffix: str = "dev"

    @property
    def version_string(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}-{self.suffix}"


def get_research_version() -> ResearchVersion:
    """Retrieve structured version information for the Python research layer."""
    return ResearchVersion()
