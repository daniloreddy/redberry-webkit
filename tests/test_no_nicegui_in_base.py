import subprocess
import sys

BASE_MODULES = ["redberry_webkit.auth", "redberry_webkit.config", "redberry_webkit.web", "redberry_webkit.bootstrap"]


def test_base_modules_import_without_nicegui() -> None:
    """nicegui is an optional extra: the Jinja2/HTMX modules must not import it."""
    code = "import sys; sys.modules['nicegui'] = None; import " + ", ".join(BASE_MODULES)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
