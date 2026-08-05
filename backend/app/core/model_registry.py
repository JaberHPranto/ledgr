import importlib
import os
import pathlib

from backend.app.core.logging import get_logger

logger = get_logger()


def discover_modules() -> list[str]:
    models_modules = []
    root_path = pathlib.Path(__file__).parent.parent

    logger.debug(f"Searching for models in the root path: {root_path}")

    for root, _, files in os.walk(root_path):
        if any(
            excluded_path in root
            for excluded_path in ["venv", "__pycache__", ".pytest_cache"]
        ):
            continue

        if "models.py" in files:
            rel_path = os.path.relpath(root, root_path)
            module_path = rel_path.replace(os.path.sep, ".")

            if module_path == ".":
                full_module_path = "backend.app.models"
            else:
                full_module_path = f"backend.app.{module_path}.models"

            logger.debug(f"Discovered models file in: {full_module_path}")

            models_modules.append(full_module_path)

    return models_modules


def load_models() -> None:
    modules = discover_modules()
    for module_path in modules:
        try:
            importlib.import_module(module_path)
            logger.debug(f"Loaded module: {module_path}")
        except Exception as e:
            logger.error(f"Failed to load module {module_path}: {e}")
