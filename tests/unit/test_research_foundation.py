"""Unit tests verifying the Python research engineering foundation."""

from research import __version__, get_research_version
from research.version import ResearchVersion


def test_research_version_structure() -> None:
    """Validate that research version data structure is accurate and immutable."""
    ver = get_research_version()
    assert isinstance(ver, ResearchVersion)
    assert ver.major == 0
    assert ver.minor == 1
    assert ver.patch == 0
    assert ver.suffix == "dev"
    assert ver.version_string == "0.1.0-dev"


def test_package_version_export() -> None:
    """Validate package __version__ export consistency."""
    assert __version__ == "0.1.0-dev"
