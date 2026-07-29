from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from crs_fatca_generator import APP_NAME


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return project_root()


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", project_root()))


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


def portable_config_path() -> Path:
    env_path = os.environ.get("CIINTEGRACAO_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return app_base_dir() / "configuracao_portatil.json"


def portable_config() -> dict[str, Any]:
    path = portable_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def configured_path(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(os.path.expandvars(text)).expanduser()
    if not path.is_absolute():
        path = app_base_dir() / path
    return path


def is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".write_test_", dir=path)
        os.close(fd)
        Path(temp_name).unlink(missing_ok=True)
        return True
    except OSError:
        return False


def config_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "sim", "s", "yes", "true"}:
        return True
    if text in {"0", "nao", "não", "n", "no", "false"}:
        return False
    return default


def user_data_dir() -> Path:
    config = portable_config()
    candidates = [
        configured_path(os.environ.get("CIINTEGRACAO_DATA_DIR")),
        configured_path(config.get("pasta_dados_local")),
    ]
    base = os.environ.get("LOCALAPPDATA")
    candidates.append((Path(base) if base else Path.home() / "AppData" / "Local") / APP_NAME.replace(" ", "_"))
    candidates.extend(
        [
            app_base_dir() / "dados_locais",
            Path.home() / "Documents" / "CRS_FATCA_XML_Generator" / "dados_locais",
            Path(tempfile.gettempdir()) / APP_NAME.replace(" ", "_"),
        ]
    )
    for path in candidates:
        if path and is_writable_dir(path):
            return path
    raise OSError("Nao foi encontrada uma pasta gravavel para dados locais.")


def default_output_dir(excel_path: Path) -> Path:
    config = portable_config()
    configured = configured_path(config.get("pasta_saida_padrao") or os.environ.get("CIINTEGRACAO_OUTPUT_DIR"))
    if configured and is_writable_dir(configured):
        return configured / excel_path.stem
    prefer_next_to_excel = config_bool(config.get("preferir_saida_ao_lado_do_excel"), True)
    next_to_excel = excel_path.parent / "XML_Gerados"
    if prefer_next_to_excel and is_writable_dir(next_to_excel):
        return next_to_excel
    documents = Path.home() / "Documents"
    fallback_root = documents if is_writable_dir(documents) else user_data_dir()
    fallback = fallback_root / "CRS_FATCA_XML_Gerados" / excel_path.stem
    if is_writable_dir(fallback):
        return fallback
    return user_data_dir() / "XML_Gerados" / excel_path.stem


def logs_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_dir() -> Path:
    path = user_data_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def diagnostics_dir() -> Path:
    path = user_data_dir() / "diagnostics"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_crs_schema() -> Path:
    return resource_path("schemas", "crs", "v3_0", "CrsXML_v3.0.xsd")


def default_fatca_schema() -> Path:
    return resource_path("schemas", "fatca", "v2_0_1", "FatcaXML_v2.0.1.xsd")
