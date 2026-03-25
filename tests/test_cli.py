"""Tests for the CLI module."""

import sys
from unittest.mock import patch

import pytest

from revision_lib.cli import main


class TestCLI:
    def test_no_command_shows_help(self, capsys):
        with patch("sys.argv", ["revision"]):
            ret = main()
        assert ret == 0

    def test_check_no_package_no_all(self, capsys):
        with patch("sys.argv", ["revision", "check"]):
            ret = main()
        assert ret == 1

    @patch("revision_lib.cli.VersionChecker")
    def test_check_package(self, MockChecker, capsys):
        from revision_lib.checker import PackageInfo
        mock = MockChecker.return_value
        mock.check_package.return_value = PackageInfo(
            name="requests",
            installed_version="2.28.0",
            latest_version="2.31.0",
            available_versions=["2.31.0", "2.28.0"],
        )
        with patch("sys.argv", ["revision", "check", "requests"]):
            ret = main()
        captured = capsys.readouterr()
        assert "requests" in captured.out
        assert "OUTDATED" in captured.out
        assert ret == 0
