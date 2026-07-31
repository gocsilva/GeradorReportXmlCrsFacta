from __future__ import annotations

from lxml import etree

from crs_fatca_generator.services.xml_helpers import CRS_NS, add, atomic_write, sanitize_xml_text, strip_invalid_xml_chars
from crs_fatca_generator.services.xml_sanitizer_service import XmlSanitizerService


def test_sanitize_xml_text_remove_caracteres_bloqueados_pelo_portal() -> None:
    raw = "Rua HÃ©lio Rodrigues Ferreira & JoÃ£o Pessoa <Teste> -- contrato /* antigo &#123;\x08\x7f\ufdd0"

    cleaned = sanitize_xml_text(raw)

    assert cleaned.startswith("Rua Helio Rodrigues Ferreira e Joao Pessoa")
    assert "&" not in cleaned
    assert "<" not in cleaned
    assert ">" not in cleaned
    assert "'" not in cleaned
    assert '"' not in cleaned
    assert "--" not in cleaned
    assert "/*" not in cleaned
    assert "&#" not in cleaned
    assert "\x08" not in cleaned
    assert "\x7f" not in cleaned
    assert "\ufdd0" not in cleaned
    assert cleaned.isascii()


def test_strip_invalid_xml_chars_preserva_faixa_valida_xml_10() -> None:
    assert strip_invalid_xml_chars("A\tB\nC\rD") == "A\tB\nC\rD"
    assert strip_invalid_xml_chars("A\ud800B") == "AB"


def test_add_sanitiza_texto_antes_de_serializar_xml() -> None:
    root = etree.Element("root")
    add(root, CRS_NS, "Name", "A&B < C > D ' E \" F -- /* &#")

    xml = etree.tostring(root, encoding="unicode")

    assert "&amp;" not in xml
    assert "&lt;" not in xml
    assert "&gt;" not in xml
    assert "--" not in root[0].text
    assert "/*" not in root[0].text
    assert "&#" not in root[0].text
    assert ">" not in root[0].text
    assert "'" not in root[0].text
    assert '"' not in root[0].text


def test_atomic_write_sanitiza_arvore_inteira_antes_de_gravar(tmp_path) -> None:
    target = tmp_path / "saida.xml"
    root = etree.Element("root")
    child = etree.SubElement(root, "Name", attrib={"valor": "A&B < C > D ' E \" F -- /* &#"})
    child.text = "Rua A&B < C > D ' E \" F -- /* &#"

    atomic_write(etree.ElementTree(root), target)

    parsed = etree.parse(str(target))
    parsed_child = parsed.getroot()[0]
    text = parsed_child.text or ""
    attr = parsed_child.get("valor") or ""
    for value in (text, attr):
        assert "&" not in value
        assert "<" not in value
        assert ">" not in value
        assert "'" not in value
        assert '"' not in value
        assert "--" not in value
        assert "/*" not in value
        assert "&#" not in value


def test_sanitize_file_limpa_xml_ja_gerado(tmp_path) -> None:
    source = tmp_path / "entrada.xml"
    target = tmp_path / "saida.xml"
    source.write_text(
        "<?xml version='1.0' encoding='UTF-8'?><root><Name>A&amp;B -- /* &#65;</Name></root>",
        encoding="utf-8",
    )

    result = XmlSanitizerService().sanitize_file(source, target)
    text = target.read_text(encoding="utf-8")

    assert result.text_nodes_changed == 1
    assert "&amp;" not in text
    assert "--" not in text
    assert "/*" not in text
    assert "&#" not in text
