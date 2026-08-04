"""Config loader. Reads config.yaml and returns it as a dict."""
import os
import yaml

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)


def load_config(path: str | None = None) -> dict:
    path = path or _DEFAULT_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
