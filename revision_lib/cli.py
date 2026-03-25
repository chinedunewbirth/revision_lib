"""
CLI interface for revision_lib.

Usage:
    revision check <package>          — Check a package for updates
    revision check --all              — Check all installed packages for updates
    revision compat <package>         — Check upgrade compatibility for a package
    revision compat <package> <ver>   — Check compatibility with a specific version
    revision env-check                — Scan environment for existing conflicts
    revision plan [packages...]       — Show upgrade plan without executing
    revision upgrade <package>        — Upgrade a package (with safety checks)
    revision upgrade --all            — Upgrade all outdated packages
    revision upgrade <pkg> --force    — Force upgrade, skip compatibility checks
"""

from __future__ import annotations

import argparse
import sys

from revision_lib.checker import VersionChecker
from revision_lib.compatibility import CompatibilityChecker
from revision_lib.upgrader import Upgrader, UpgradeStatus


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="revision",
        description="Automate Python library upgrades and check version compatibility.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- check ---
    check_p = sub.add_parser("check", help="Check package versions")
    check_p.add_argument("package", nargs="?", help="Package name to check")
    check_p.add_argument(
        "--all", action="store_true", dest="check_all",
        help="Check all installed packages for updates",
    )

    # --- compat ---
    compat_p = sub.add_parser("compat", help="Check upgrade compatibility")
    compat_p.add_argument("package", help="Package name")
    compat_p.add_argument("version", nargs="?", default=None, help="Target version")

    # --- env-check ---
    sub.add_parser("env-check", help="Scan environment for dependency conflicts")

    # --- plan ---
    plan_p = sub.add_parser("plan", help="Show upgrade plan (dry run)")
    plan_p.add_argument("packages", nargs="*", help="Packages to plan (default: all outdated)")

    # --- upgrade ---
    upgrade_p = sub.add_parser("upgrade", help="Upgrade packages")
    upgrade_p.add_argument("package", nargs="?", help="Package to upgrade")
    upgrade_p.add_argument(
        "--all", action="store_true", dest="upgrade_all",
        help="Upgrade all outdated packages",
    )
    upgrade_p.add_argument(
        "--force", action="store_true",
        help="Force upgrade even with compatibility conflicts",
    )
    upgrade_p.add_argument(
        "--version", dest="target_version", default=None,
        help="Specific version to upgrade to",
    )

    return parser


def cmd_check(args: argparse.Namespace) -> int:
    checker = VersionChecker()

    if args.check_all:
        print("Scanning all installed packages for updates...\n")
        outdated = checker.find_outdated()
        if not outdated:
            print("All packages are up to date.")
            return 0
        print(f"{'Package':<30} {'Installed':<15} {'Latest':<15}")
        print("-" * 60)
        for pkg in outdated:
            print(f"{pkg.name:<30} {pkg.installed_version:<15} {pkg.latest_version:<15}")
        print(f"\n{len(outdated)} package(s) can be upgraded.")
        return 0

    if not args.package:
        print("Error: Provide a package name or use --all", file=sys.stderr)
        return 1

    info = checker.check_package(args.package)
    print(f"Package:   {info.name}")
    print(f"Installed: {info.installed_version or 'not installed'}")
    print(f"Latest:    {info.latest_version or 'unknown'}")
    if info.is_outdated:
        print(f"Status:    OUTDATED (upgrade available to {info.latest_version})")
    elif info.installed_version and info.latest_version:
        print("Status:    UP TO DATE")
    return 0


def cmd_compat(args: argparse.Namespace) -> int:
    compat = CompatibilityChecker()
    report = compat.check_upgrade_compatibility(args.package, args.version)

    target = report.target_version
    print(f"Compatibility check: {args.package} -> {target}\n")

    if report.is_compatible:
        print("COMPATIBLE — No conflicts detected.")
    else:
        print(f"CONFLICTS FOUND ({len(report.conflicts)}):\n")
        for c in report.conflicts:
            print(f"  - {c.reason}")

    if report.warnings:
        print(f"\nWarnings ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  - {w}")

    return 0 if report.is_compatible else 1


def cmd_env_check(_args: argparse.Namespace) -> int:
    compat = CompatibilityChecker()
    print("Scanning environment for dependency conflicts...\n")
    conflicts = compat.full_environment_check()

    if not conflicts:
        print("No conflicts detected. Environment is healthy.")
        return 0

    print(f"Found {len(conflicts)} conflict(s):\n")
    for c in conflicts:
        print(f"  - {c.reason}")
    return 1


def cmd_plan(args: argparse.Namespace) -> int:
    upgrader = Upgrader()
    packages = args.packages if args.packages else None
    print("Computing upgrade plan...\n")
    plan = upgrader.plan_upgrades(packages)

    if not plan.upgrades:
        print("Nothing to upgrade.")
        return 0

    print(f"{'Package':<30} {'From':<15} {'To':<15} {'Status':<20}")
    print("-" * 80)
    for r in plan.upgrades:
        print(
            f"{r.package:<30} "
            f"{r.from_version or 'N/A':<15} "
            f"{r.to_version or 'N/A':<15} "
            f"{r.status.value:<20}"
        )
        if r.compatibility_report and r.compatibility_report.conflicts:
            for c in r.compatibility_report.conflicts:
                print(f"    CONFLICT: {c.reason}")

    print(f"\nSummary: {plan.summary}")
    return 1 if plan.has_conflicts else 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    upgrader = Upgrader()

    if args.upgrade_all:
        print("Upgrading all outdated packages...\n")
        results = upgrader.upgrade_packages(force=args.force)
    elif args.package:
        results = [
            upgrader.upgrade_package(
                args.package,
                target_version=args.target_version,
                force=args.force,
            )
        ]
    else:
        print("Error: Provide a package name or use --all", file=sys.stderr)
        return 1

    for r in results:
        icon = {
            UpgradeStatus.SUCCESS: "[OK]",
            UpgradeStatus.SKIPPED_COMPATIBLE: "[SKIP]",
            UpgradeStatus.SKIPPED_CONFLICT: "[CONFLICT]",
            UpgradeStatus.FAILED: "[FAIL]",
            UpgradeStatus.DRY_RUN: "[DRY]",
        }.get(r.status, "[?]")

        print(f"  {icon} {r.package}: {r.from_version} -> {r.to_version}  ({r.status.value})")
        if r.error:
            print(f"       Error: {r.error}")
        if r.compatibility_report and r.compatibility_report.conflicts:
            for c in r.compatibility_report.conflicts:
                print(f"       Conflict: {c.reason}")

    success_count = sum(1 for r in results if r.status == UpgradeStatus.SUCCESS)
    print(f"\n{success_count}/{len(results)} package(s) upgraded successfully.")
    return 0 if all(r.status in (UpgradeStatus.SUCCESS, UpgradeStatus.SKIPPED_COMPATIBLE) for r in results) else 1


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    handlers = {
        "check": cmd_check,
        "compat": cmd_compat,
        "env-check": cmd_env_check,
        "plan": cmd_plan,
        "upgrade": cmd_upgrade,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
