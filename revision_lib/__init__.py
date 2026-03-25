"""
revision_lib - Automate Python library upgrades and check version compatibility.
"""

__version__ = "0.1.0"

from revision_lib.checker import VersionChecker
from revision_lib.compatibility import CompatibilityChecker
from revision_lib.upgrader import Upgrader

__all__ = ["VersionChecker", "CompatibilityChecker", "Upgrader"]
