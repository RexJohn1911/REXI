"""REXI Quantitative Research Engine Foundation."""

from research.version import ResearchVersion, get_research_version

__version__ = get_research_version().version_string
__all__ = ["ResearchVersion", "__version__", "get_research_version"]
