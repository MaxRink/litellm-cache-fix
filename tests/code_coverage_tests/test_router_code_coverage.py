from pathlib import Path

from router_code_coverage import add_class_method_aliases


def test_class_method_aliases_map_public_calls_to_private_implementation(tmp_path: Path) -> None:
    router = tmp_path / "router.py"
    router.write_text(
        """
class Router:
    def _private_behavior(self):
        return None

    public_behavior = _private_behavior

    def uncalled_behavior(self):
        return None
""",
        encoding="utf-8",
    )

    called = add_class_method_aliases({"public_behavior"}, str(router))

    assert "_private_behavior" in called
    assert "uncalled_behavior" not in called
