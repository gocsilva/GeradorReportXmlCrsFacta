from __future__ import annotations

from lxml import etree

from crs_fatca_generator.services.xml_helpers import CRS_NS, add, sanitize_xml_text


def test_sanitize_xml_text_remove_caracteres_bloqueados_pelo_portal() -> None:
    raw = "Cliente A&B <Teste> -- contrato /* antigo &#123;"

    cleaned = sanitize_xml_text(raw)

    assert "&" not in cleaned
    assert "<" not in cleaned
    assert "--" not in cleaned
    assert "/*" not in cleaned
    assert "&#" not in cleaned


def test_add_sanitiza_texto_antes_de_serializar_xml() -> None:
    root = etree.Element("root")
    add(root, CRS_NS, "Name", "A&B < C -- /* &#")

    xml = etree.tostring(root, encoding="unicode")

    assert "&amp;" not in xml
    assert "&lt;" not in xml
    assert "--" not in root[0].text
    assert "/*" not in root[0].text
    assert "&#" not in root[0].text
