"""
Version checking module - inspects installed packages and queries PyPI for updates.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import requests
from packaging.version import Version, InvalidVersion

logger = logging.getLogger(__name__)

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"


@dataclass
class PackageInfo:
    """Holds version information for a single package."""

    name: str
    installed_version: Optional[str] = None
    latest_version: Optional[str] = None
    available_versions: List[str] = field(default_factory=list)

    @property
    def is_outdated(self) -> bool:
        """Return True if the installed version is older than the latest."""
        if self.installed_version is None or self.latest_version is None:
            return False
        try:
            return Version(self.installed_version) < Version(self.latest_version)
        except InvalidVersion:
            return False

    @property
    def upgrade_available(self) -> Optional[str]:
        """Return the latest version string if an upgrade is available, else None."""
        return self.latest_version if self.is_outdated else None


class VersionChecker:
    """Check installed package versions and compare with PyPI."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self._session = requests.Session()

    def get_installed_version(self, package_name: str) -> Optional[str]:
        """Return the currently installed version of a package, or None."""
        try:
            return importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            return None

    def get_installed_packages(self) -> Dict[str, str]:
        """Return a dict of all installed packages {name: version}."""
        packages = {}
        for dist in importlib.metadata.distributions():
            name = dist.metadata["Name"]
            version = dist.metadata["Version"]
            if name and version:
                packages[name] = version
        return packages

    def fetch_pypi_info(self, package_name: str) -> Optional[dict]:
        """Fetch package metadata from PyPI. Returns the JSON dict or None."""
        url = PYPI_JSON_URL.format(package=package_name)
        try:
            resp = self._session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.warning("Failed to fetch PyPI info for %s: %s", package_name, exc)
            return None

    def get_latest_version(self, package_name: str) -> Optional[str]:
        """Return the latest stable version string from PyPI, or None."""
        data = self.fetch_pypi_info(package_name)
        if data is None:
            return None
        return data.get("info", {}).get("version")

    def get_available_versions(self, package_name: str) -> List[str]:
        """Return all released version strings from PyPI, sorted descending."""
        data = self.fetch_pypi_info(package_name)
        if data is None:
            return []
        releases = data.get("releases", {})
        versions = []
        for v in releases:
            try:
                versions.append(Version(v))
            except InvalidVersion:
                continue
        versions.sort(reverse=True)
        return [str(v) for v in versions]

    def check_package(self, package_name: str) -> PackageInfo:
        """Return full version info for a single package."""
        installed = self.get_installed_version(package_name)
        latest = self.get_latest_version(package_name)
        available = self.get_available_versions(package_name)
        return PackageInfo(
            name=package_name,
            installed_version=installed,
            latest_version=latest,
            available_versions=available,
        )

    def check_packages(self, package_names: List[str]) -> List[PackageInfo]:
        """Check multiple packages and return their info."""
        return [self.check_package(name) for name in package_names]

    def find_outdated(self) -> List[PackageInfo]:
        """Scan all installed packages and return those that are outdated."""
        outdated = []
        installed = self.get_installed_packages()
        for name, version in installed.items():
            latest = self.get_latest_version(name)
            info = PackageInfo(
                name=name,
                installed_version=version,
                latest_version=latest,
            )
            if info.is_outdated:
                outdated.append(info)
        return outdated
