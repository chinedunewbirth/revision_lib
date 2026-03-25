"""Tests for the upgrader module."""

from unittest.mock import MagicMock, patch

import pytest

from revision_lib.checker import PackageInfo, VersionChecker
from revision_lib.compatibility import CompatibilityChecker, CompatibilityReport
from revision_lib.upgrader import Upgrader, UpgradeStatus, UpgradePlan, UpgradeResult


class TestUpgradeResult:
    def test_upgrade_plan_summary(self):
        plan = UpgradePlan(upgrades=[
            UpgradeResult(package="a", status=UpgradeStatus.SUCCESS),
            UpgradeResult(package="b", status=UpgradeStatus.SUCCESS),
            UpgradeResult(package="c", status=UpgradeStatus.SKIPPED_CONFLICT),
        ])
        assert plan.summary == {"success": 2, "skipped_conflict": 1}
        assert plan.has_conflicts is True

    def test_upgrade_plan_no_conflicts(self):
        plan = UpgradePlan(upgrades=[
            UpgradeResult(package="a", status=UpgradeStatus.SUCCESS),
        ])
        assert plan.has_conflicts is False


class TestUpgrader:
    def _make_upgrader(self):
        checker = MagicMock(spec=VersionChecker)
        compat = MagicMock(spec=CompatibilityChecker)
        upgrader = Upgrader(checker=checker, compat_checker=compat)
        return upgrader, checker, compat

    def test_plan_upgrade_already_latest(self):
        upgrader, checker, compat = self._make_upgrader()
        checker.check_package.return_value = PackageInfo(
            name="foo", installed_version="2.0.0", latest_version="2.0.0"
        )
        result = upgrader.plan_upgrade("foo")
        assert result.status == UpgradeStatus.SKIPPED_COMPATIBLE

    def test_plan_upgrade_no_target(self):
        upgrader, checker, compat = self._make_upgrader()
        checker.check_package.return_value = PackageInfo(
            name="foo", installed_version="1.0.0", latest_version=None
        )
        result = upgrader.plan_upgrade("foo")
        assert result.status == UpgradeStatus.FAILED

    def test_plan_upgrade_conflict(self):
        upgrader, checker, compat = self._make_upgrader()
        checker.check_package.return_value = PackageInfo(
            name="foo", installed_version="1.0.0", latest_version="2.0.0"
        )
        report = CompatibilityReport(package="foo", target_version="2.0.0")
        report.conflicts.append(MagicMock())
        compat.check_upgrade_compatibility.return_value = report

        result = upgrader.plan_upgrade("foo")
        assert result.status == UpgradeStatus.SKIPPED_CONFLICT

    def test_plan_upgrade_dry_run(self):
        upgrader, checker, compat = self._make_upgrader()
        checker.check_package.return_value = PackageInfo(
            name="foo", installed_version="1.0.0", latest_version="2.0.0"
        )
        report = CompatibilityReport(package="foo", target_version="2.0.0")
        compat.check_upgrade_compatibility.return_value = report

        result = upgrader.plan_upgrade("foo")
        assert result.status == UpgradeStatus.DRY_RUN
        assert result.to_version == "2.0.0"

    @patch.object(Upgrader, "_run_pip")
    def test_upgrade_package_success(self, mock_pip):
        upgrader, checker, compat = self._make_upgrader()
        upgrader._run_pip = mock_pip
        checker.check_package.return_value = PackageInfo(
            name="foo", installed_version="1.0.0", latest_version="2.0.0"
        )
        report = CompatibilityReport(package="foo", target_version="2.0.0")
        compat.check_upgrade_compatibility.return_value = report
        mock_pip.return_value = MagicMock(returncode=0, stderr="")

        result = upgrader.upgrade_package("foo")
        assert result.status == UpgradeStatus.SUCCESS

    @patch.object(Upgrader, "_run_pip")
    def test_upgrade_package_pip_failure(self, mock_pip):
        upgrader, checker, compat = self._make_upgrader()
        upgrader._run_pip = mock_pip
        checker.check_package.return_value = PackageInfo(
            name="foo", installed_version="1.0.0", latest_version="2.0.0"
        )
        report = CompatibilityReport(package="foo", target_version="2.0.0")
        compat.check_upgrade_compatibility.return_value = report
        mock_pip.return_value = MagicMock(returncode=1, stderr="install error")

        result = upgrader.upgrade_package("foo")
        assert result.status == UpgradeStatus.FAILED
        assert "install error" in result.error
