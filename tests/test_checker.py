"""Tests for the version checker module."""

from unittest.mock import MagicMock, patch

import pytest

from revision_lib.checker import PackageInfo, VersionChecker


# --- PackageInfo tests ---

class TestPackageInfo:
    def test_is_outdated_true(self):
        info = PackageInfo(name="foo", installed_version="1.0.0", latest_version="2.0.0")
        assert info.is_outdated is True

    def test_is_outdated_false_when_current(self):
        info = PackageInfo(name="foo", installed_version="2.0.0", latest_version="2.0.0")
        assert info.is_outdated is False

    def test_is_outdated_false_when_none(self):
        info = PackageInfo(name="foo", installed_version=None, latest_version="2.0.0")
        assert info.is_outdated is False

    def test_upgrade_available(self):
        info = PackageInfo(name="foo", installed_version="1.0.0", latest_version="2.0.0")
        assert info.upgrade_available == "2.0.0"

    def test_no_upgrade_available(self):
        info = PackageInfo(name="foo", installed_version="2.0.0", latest_version="2.0.0")
        assert info.upgrade_available is None


# --- VersionChecker tests ---

class TestVersionChecker:
    def test_get_installed_version_existing(self):
        checker = VersionChecker()
        # pip is always installed
        version = checker.get_installed_version("pip")
        assert version is not None

    def test_get_installed_version_missing(self):
        checker = VersionChecker()
        version = checker.get_installed_version("nonexistent_package_xyz_12345")
        assert version is None

    def test_get_installed_packages(self):
        checker = VersionChecker()
        packages = checker.get_installed_packages()
        assert isinstance(packages, dict)
        assert "pip" in packages

    @patch.object(VersionChecker, "fetch_pypi_info")
    def test_get_latest_version(self, mock_fetch):
        mock_fetch.return_value = {"info": {"version": "3.5.0"}}
        checker = VersionChecker()
        assert checker.get_latest_version("some-pkg") == "3.5.0"

    @patch.object(VersionChecker, "fetch_pypi_info")
    def test_get_latest_version_none(self, mock_fetch):
        mock_fetch.return_value = None
        checker = VersionChecker()
        assert checker.get_latest_version("some-pkg") is None

    @patch.object(VersionChecker, "fetch_pypi_info")
    def test_get_available_versions(self, mock_fetch):
        mock_fetch.return_value = {
            "releases": {"1.0.0": [], "2.0.0": [], "1.5.0": [], "invalid": []}
        }
        checker = VersionChecker()
        versions = checker.get_available_versions("some-pkg")
        assert versions == ["2.0.0", "1.5.0", "1.0.0"]

    @patch.object(VersionChecker, "fetch_pypi_info")
    def test_check_package(self, mock_fetch):
        mock_fetch.return_value = {
            "info": {"version": "99.0.0"},
            "releases": {"99.0.0": [], "98.0.0": []},
        }
        checker = VersionChecker()
        info = checker.check_package("pip")
        assert info.name == "pip"
        assert info.installed_version is not None
        assert info.latest_version == "99.0.0"
