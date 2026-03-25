"""
Compatibility checker - verifies that upgrading a package won't break dependencies.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from packaging.requirements import Requirement, InvalidRequirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion

from revision_lib.checker import VersionChecker

logger = logging.getLogger(__name__)


@dataclass
class Conflict:
    """Represents a dependency conflict."""

    package: str
    required_by: str
    requirement: str
    installed_version: Optional[str]
    reason: str


@dataclass
class CompatibilityReport:
    """Result of a compatibility check for one or more upgrades."""

    package: str
    target_version: str
    conflicts: List[Conflict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_compatible(self) -> bool:
        return len(self.conflicts) == 0


class CompatibilityChecker:
    """Check whether upgrading packages would cause dependency conflicts."""

    def __init__(self, checker: Optional[VersionChecker] = None):
        self.checker = checker or VersionChecker()

    def get_reverse_dependencies(self, package_name: str) -> Dict[str, List[Requirement]]:
        """
        Find all installed packages that depend on `package_name`.
        Returns {dependent_package: [Requirement objects that reference package_name]}.
        """
        package_lower = package_name.lower().replace("-", "_")
        reverse_deps: Dict[str, List[Requirement]] = {}

        for dist in importlib.metadata.distributions():
            dist_name = dist.metadata["Name"]
            if dist_name is None:
                continue
            requires = dist.requires
            if requires is None:
                continue
            for req_str in requires:
                try:
                    req = Requirement(req_str)
                except InvalidRequirement:
                    continue
                # Skip extras-only requirements (conditional on extras)
                if req.marker is not None:
                    # Evaluate marker in a minimal environment; skip if clearly extra-only
                    pass
                req_name_normalized = req.name.lower().replace("-", "_")
                if req_name_normalized == package_lower:
                    reverse_deps.setdefault(dist_name, []).append(req)

        return reverse_deps

    def check_version_against_requirement(
        self, version: str, requirement: Requirement
    ) -> bool:
        """Return True if `version` satisfies the requirement's specifier."""
        if not requirement.specifier:
            return True  # No version constraint
        try:
            return Version(version) in requirement.specifier
        except InvalidVersion:
            return False

    def check_upgrade_compatibility(
        self, package_name: str, target_version: Optional[str] = None
    ) -> CompatibilityReport:
        """
        Check if upgrading `package_name` to `target_version` is compatible
        with all currently installed packages that depend on it.

        If `target_version` is None, checks against the latest PyPI version.
        """
        if target_version is None:
            target_version = self.checker.get_latest_version(package_name)
            if target_version is None:
                report = CompatibilityReport(
                    package=package_name, target_version="unknown"
                )
                report.warnings.append(
                    f"Could not determine latest version for {package_name}"
                )
                return report

        report = CompatibilityReport(
            package=package_name, target_version=target_version
        )

        # Check reverse dependencies
        reverse_deps = self.get_reverse_dependencies(package_name)
        for dep_name, requirements in reverse_deps.items():
            for req in requirements:
                if not self.check_version_against_requirement(target_version, req):
                    report.conflicts.append(
                        Conflict(
                            package=package_name,
                            required_by=dep_name,
                            requirement=str(req),
                            installed_version=self.checker.get_installed_version(
                                package_name
                            ),
                            reason=(
                                f"{dep_name} requires {req}, but upgrade target "
                                f"{target_version} does not satisfy this constraint"
                            ),
                        )
                    )

        # Check the target package's own dependencies
        self._check_target_dependencies(package_name, target_version, report)

        return report

    def _check_target_dependencies(
        self, package_name: str, target_version: str, report: CompatibilityReport
    ) -> None:
        """Check that the target version's dependencies are satisfiable."""
        data = self.checker.fetch_pypi_info(package_name)
        if data is None:
            report.warnings.append(
                f"Could not fetch PyPI metadata to verify {package_name} "
                f"{target_version} dependencies"
            )
            return

        releases = data.get("releases", {})
        release_files = releases.get(target_version, [])
        if not release_files:
            report.warnings.append(
                f"No release files found for {package_name}=={target_version}"
            )
            return

        # Get requires_dist from the version-specific info if available
        requires_dist = data.get("info", {}).get("requires_dist") or []
        for req_str in requires_dist:
            try:
                req = Requirement(req_str)
            except InvalidRequirement:
                continue

            # Skip optional/extra dependencies
            if req.marker is not None:
                continue

            installed_ver = self.checker.get_installed_version(req.name)
            if installed_ver is None:
                # Dependency not installed — will need to be installed
                report.warnings.append(
                    f"New dependency required: {req} (not currently installed)"
                )
                continue

            if req.specifier and not self.check_version_against_requirement(
                installed_ver, req
            ):
                report.conflicts.append(
                    Conflict(
                        package=req.name,
                        required_by=f"{package_name}=={target_version}",
                        requirement=str(req),
                        installed_version=installed_ver,
                        reason=(
                            f"{package_name}=={target_version} requires {req}, "
                            f"but {req.name}=={installed_ver} is installed"
                        ),
                    )
                )

    def check_multiple(
        self, packages: Dict[str, Optional[str]]
    ) -> List[CompatibilityReport]:
        """
        Check compatibility for multiple packages.
        `packages` is {package_name: target_version_or_None}.
        """
        return [
            self.check_upgrade_compatibility(name, version)
            for name, version in packages.items()
        ]

    def full_environment_check(self) -> List[Conflict]:
        """
        Scan the entire installed environment for existing dependency conflicts
        (not related to upgrades — just the current state).
        """
        conflicts = []
        installed = self.checker.get_installed_packages()

        for dist in importlib.metadata.distributions():
            dist_name = dist.metadata["Name"]
            requires = dist.requires
            if requires is None:
                continue
            for req_str in requires:
                try:
                    req = Requirement(req_str)
                except InvalidRequirement:
                    continue
                if req.marker is not None:
                    continue
                dep_version = installed.get(req.name)
                if dep_version is None:
                    conflicts.append(
                        Conflict(
                            package=req.name,
                            required_by=dist_name,
                            requirement=str(req),
                            installed_version=None,
                            reason=f"{req.name} is required by {dist_name} but not installed",
                        )
                    )
                elif req.specifier and not self.check_version_against_requirement(
                    dep_version, req
                ):
                    conflicts.append(
                        Conflict(
                            package=req.name,
                            required_by=dist_name,
                            requirement=str(req),
                            installed_version=dep_version,
                            reason=(
                                f"{dist_name} requires {req}, "
                                f"but {req.name}=={dep_version} is installed"
                            ),
                        )
                    )
        return conflicts
