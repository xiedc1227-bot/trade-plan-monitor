from importlib import import_module
from importlib.metadata import version


def test_package_version_matches_distribution_metadata() -> None:
    package = import_module("trade_plan_monitor")

    assert package.__version__ == "0.1.0"
    assert version("trade-plan-monitor") == package.__version__


def test_main_module_exposes_a_no_op_entrypoint() -> None:
    main_module = import_module("trade_plan_monitor.__main__")

    assert main_module.main() == 0
