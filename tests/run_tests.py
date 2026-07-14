from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"

sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    test_package = importlib.import_module("tests")

    failures = []

    print()

    for module in sorted(
        pkgutil.iter_modules(test_package.__path__),
        key=lambda m: m.name,
    ):
        if (
            not module.name.startswith("test_")
            or module.name == "run_tests"
        ):
            continue

        print(f"Running {module.name}...")

        imported = importlib.import_module(
            f"tests.{module.name}"
        )

        try:
            imported.run()
        except Exception as error:
            failures.append((module.name, error))
            print(f"  ✗ {error}")
        else:
            print("  ✓ Passed")

        print()

    if failures:
        print("=" * 60)
        print("FAILED")
        print()

        for module_name, error in failures:
            print(f"{module_name}: {error}")

        return 1

    print("=" * 60)
    print("All regression tests passed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())