from importlib import import_module


def test_cari_package_can_be_imported() -> None:
    import_module("cari")
