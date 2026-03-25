"""
Upgrade automation module - safely upgrades packages with compatibility checks.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from revision_lib.checker import PackageInfo, VersionChecker
from revision_lib.compatibility import CompatibilityChecker, CompatibilityReport

logger = logging.getLogger(__name__)


class UpgradeStatus(Enum):
    SUCCESS = "success"
    SKIPPED_COMPATIBLE = "skipped_already_latest"
    SKIPPED_CONFLICT = "skipped_conflict"
    FAILED = "failed"
    DRY_RUN = "dry_run"


@dataclass
class UpgradeResult:
    """Result of an upgrade attempt for a single package."""

    package: str
    status: UpgradeStatus
    from_version: Optional[str] = None
    to_version: Optional[str] = None
    compatibility_report: Optional[CompatibilityReport] = None
    error: Optional[str] = None


@dataclass
class UpgradePlan:
    """A plan showing what would happen if upgrades are executed."""

    upgrades: List[UpgradeResult] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return any(
            r.status == UpgradeStatus.SKIPPED_CONFLICT for r in self.upgrades
        )

    @property
    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self.upgrades:
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        return counts


class Upgrader:
    """Automates safe package upgrades with pre-flight compatibility checks."""

    def __init__(
        self,
        checker: Optional[VersionChecker] = None,
        compat_checker: Optional[CompatibilityChecker] = None,
        python_executable: Optional[str] = None,
    ):
        self.checker = checker or VersionChecker()
        self.compat_checker = compat_checker or CompatibilityChecker(self.checker)
        self.python_executable = python_executable or sys.executable

    def _run_pip(self, args: List[str]) -> subprocess.CompletedProcess:
        """Run a pip command safely using the current Python interpreter."""
        cmd = [self.python_executable, "-m", "pip"] + args
        logger.info("Running: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def plan_upgrade(
        self,
        package_name: str,
        target_version: Optional[str] = None,
    ) -> UpgradeResult:
        """
        Plan an upgrade for one package. Checks compatibility but doesn't install.
        """
        info = self.checker.check_package(package_name)

        if target_version is None:
            target_version = info.latest_version

        if target_version is None:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.FAILED,
                from_version=info.installed_version,
                error=f"Could not determine target version for {package_name}",
            )

        # Already at target
        if info.installed_version == target_version:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.SKIPPED_COMPATIBLE,
                from_version=info.installed_version,
                to_version=target_version,
            )

        # Check compatibility
        report = self.compat_checker.check_upgrade_compatibility(
            package_name, target_version
        )

        if not report.is_compatible:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.SKIPPED_CONFLICT,
                from_version=info.installed_version,
                to_version=target_version,
                compatibility_report=report,
            )

        return UpgradeResult(
            package=package_name,
            status=UpgradeStatus.DRY_RUN,
            from_version=info.installed_version,
            to_version=target_version,
            compatibility_report=report,
        )

    def plan_upgrades(
        self, packages: Optional[List[str]] = None
    ) -> UpgradePlan:
        """
        Plan upgrades for multiple packages or all outdated packages.
        Returns an UpgradePlan without executing any upgrades.
        """
        if packages is None:
            outdated = self.checker.find_outdated()
            packages = [p.name for p in outdated]

        plan = UpgradePlan()
        for pkg in packages:
            result = self.plan_upgrade(pkg)
            plan.upgrades.append(result)
        return plan

    def upgrade_package(
        self,
        package_name: str,
        target_version: Optional[str] = None,
        force: bool = False,
    ) -> UpgradeResult:
        """
        Upgrade a single package. Checks compatibility first unless `force=True`.
        """
        info = self.checker.check_package(package_name)

        if target_version is None:
            target_version = info.latest_version

        if target_version is None:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.FAILED,
                from_version=info.installed_version,
                error=f"Could not determine target version for {package_name}",
            )

        # Already at target
        if info.installed_version == target_version:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.SKIPPED_COMPATIBLE,
                from_version=info.installed_version,
                to_version=target_version,
            )

        # Compatibility check
        report = self.compat_checker.check_upgrade_compatibility(
            package_name, target_version
        )

        if not report.is_compatible and not force:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.SKIPPED_CONFLICT,
                from_version=info.installed_version,
                to_version=target_version,
                compatibility_report=report,
            )

        # Perform the upgrade
        try:
            result = self._run_pip(
                ["install", f"{package_name}=={target_version}"]
            )
            if result.returncode != 0:
                return UpgradeResult(
                    package=package_name,
                    status=UpgradeStatus.FAILED,
                    from_version=info.installed_version,
                    to_version=target_version,
                    compatibility_report=report,
                    error=result.stderr.strip(),
                )
        except subprocess.TimeoutExpired:
            return UpgradeResult(
                package=package_name,
                status=UpgradeStatus.FAILED,
                from_version=info.installed_version,
                to_version=target_version,
                error="pip install timed out",
            )

        return UpgradeResult(
            package=package_name,
            status=UpgradeStatus.SUCCESS,
            from_version=info.installed_version,
            to_version=target_version,
            compatibility_report=report,
        )

    def upgrade_packages(
        self,
        packages: Optional[List[str]] = None,
        force: bool = False,
    ) -> List[UpgradeResult]:
        """
        Upgrade multiple packages (or all outdated if packages is None).
        Checks compatibility for each before upgrading.
        """
        if packages is None:
            outdated = self.checker.find_outdated()
            packages = [p.name for p in outdated]

        results = []
        for pkg in packages:
            result = self.upgrade_package(pkg, force=force)
            results.append(result)
        return results
