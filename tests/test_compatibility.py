"""Tests for the compatibility checker module."""

from unittest.mock import MagicMock, patch

import pytest
from packaging.requirements import Requirement

from revision_lib.compatibility import CompatibilityChecker, CompatibilityReport, Conflict


class TestCompatibilityChecker:
    def test_check_version_against_requirement_satisfied(self):
        compat = CompatibilityChecker()
        req = Requirement("requests>=2.0,<3.0")
        assert compat.check_version_against_requirement("2.28.0", req) is True

    def test_check_version_against_requirement_not_satisfied(self):
        compat = CompatibilityChecker()
        req = Requirement("requests>=2.0,<3.0")
        assert compat.check_version_against_requirement("3.0.0", req) is False

    def test_check_version_against_requirement_no_specifier(self):
        compat = CompatibilityChecker()
        req = Requirement("requests")
        assert compat.check_version_against_requirement("999.0.0", req) is True

    def test_get_reverse_dependencies(self):
        compat = CompatibilityChecker()
        # pip is depended on by very few packages, but the method should return a dict
        result = compat.get_reverse_dependencies("pip")
        assert isinstance(result, dict)

    @patch("revision_lib.compatibility.VersionChecker")
    def test_check_upgrade_compatibility_no_latest(self, MockChecker):
        mock_checker = MockChecker.return_value
        mock_checker.get_latest_version.return_value = None
        compat = CompatibilityChecker(checker=mock_checker)
        report = compat.check_upgrade_compatibility("fakepkg")
        assert report.target_version == "unknown"
        assert len(report.warnings) > 0

    def test_compatibility_report_is_compatible(self):
        report = CompatibilityReport(package="foo", target_version="2.0.0")
        assert report.is_compatible is True

    def test_compatibility_report_with_conflict(self):
        report = CompatibilityReport(
            package="foo",
            target_version="2.0.0",
            conflicts=[
                Conflict(
                    package="foo",
                    required_by="bar",
                    requirement="foo<2.0",
                    installed_version="1.5.0",
                    reason="bar requires foo<2.0",
                )
            ],
        )
        assert report.is_compatible is False

    def test_full_environment_check_returns_list(self):
        compat = CompatibilityChecker()
        conflicts = compat.full_environment_check()
        assert isinstance(conflicts, list)
