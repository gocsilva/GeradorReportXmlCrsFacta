from __future__ import annotations

import pytest

from crs_fatca_generator.services.transformation_service import (
    apply_transformations,
    split_values,
    to_bool,
    to_date,
    to_decimal,
)


def test_decimal_brasileiro() -> None:
    assert to_decimal("1.234,56") == "1234.56"


def test_booleanos() -> None:
    assert to_bool("SIM") == "true"
    assert to_bool("não") == "false"


def test_data() -> None:
    assert to_date("31/12/2025") == "2025-12-31"


def test_multiplos_valores() -> None:
    assert split_values("BR; US|KY") == ["BR", "US", "KY"]


def test_transformacao_desconhecida_falha() -> None:
    with pytest.raises(ValueError):
        apply_transformations("x", ["inexistente"])
