"""Storage backends for large-document line stores."""
from .compact import CompactLines
from .mapped import MappedLines

__all__ = ["CompactLines", "MappedLines"]
