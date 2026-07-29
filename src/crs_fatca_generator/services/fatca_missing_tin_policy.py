from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crs_fatca_generator.models.domain import TIN, ValidationIssue
from crs_fatca_generator.models.mapping import MappingProfile
from crs_fatca_generator.security.masking import mask_value
from crs_fatca_generator.services.tax_identifier_service import digits_only, validate_cnpj, validate_cpf
from crs_fatca_generator.services.transformation_service import country_code, normalize_text


DEFAULT_MISSING_US_TIN_POLICY = "BLOCK_PRODUCTION"
TECHNICAL_TEST_POLICY = "TECHNICAL_TEST_ONLY"
VALID_US_TIN_STATUSES = {
    "INFORMED",
    "NOT_COLLECTED",
    "NOT_AVAILABLE",
    "PENDING_FISCAL_REVIEW",
    "NOT_APPLICABLE",
    "INVALID",
}
VALID_MISSING_US_TIN_POLICIES = {
    "OMIT_ELEMENT",
    "EMPTY_ELEMENT",
    "OFFICIAL_MISSING_CODE",
    "BLOCK_PRODUCTION",
    TECHNICAL_TEST_POLICY,
    # Legacy aliases accepted to keep older profiles readable.
    "BLOCK_GENERATION",
    "OMIT_IF_SCHEMA_ALLOWS",
    "GENERATE_EMPTY_IF_SCHEMA_ALLOWS",
    "USE_OFFICIAL_REASON_CODE",
    "PENDING_FISCAL_CONFIRMATION",
}
FORBIDDEN_PLACEHOLDERS = {"", "0" * 9, "9" * 9, "NULL", "N/A", "NA", "SEM TIN", "SEM_TIN", "NONE"}


@dataclass(frozen=True)
class FatcaTinDecision:
    tins: list[TIN]
    status: str
    reason: str
    policy: str
    treatment: str
    xml_element: str
    blocking: bool
    issue: ValidationIssue | None = None


class FatcaMissingTinPolicy:
    def decide_xml_representation(self, row: dict[str, Any], profile: MappingProfile) -> FatcaTinDecision:
        policy = _normalize_policy(_profile_value(profile, row, "fatca.missing_us_tin_policy", DEFAULT_MISSING_US_TIN_POLICY).upper() or DEFAULT_MISSING_US_TIN_POLICY)
        if policy not in VALID_MISSING_US_TIN_POLICIES:
            return self._invalid(row, policy, "Politica FATCA para US TIN ausente invalida.")

        raw_tin = _profile_value(profile, row, "fatca.us_tin", "")
        issued_by = country_code(_profile_value(profile, row, "fatca.us_tin_issued_by", "US") or "US")
        status = (_profile_value(profile, row, "fatca.us_tin_status", "NOT_COLLECTED") or "NOT_COLLECTED").upper()
        reason = _profile_value(profile, row, "fatca.us_tin_reason", "")

        if status not in VALID_US_TIN_STATUSES:
            return self._invalid(row, status, "Status do US Tax ID invalido.")

        normalized = _normalize_us_tin(raw_tin)
        if normalized:
            problem = self._invalid_us_tin_reason(row, normalized, issued_by)
            if problem:
                return self._invalid(row, "INVALID", problem)
            return FatcaTinDecision(
                tins=[TIN(normalized, "US")],
                status="INFORMED",
                reason=reason,
                policy=policy,
                treatment="US Tax ID informado e preservado como texto.",
                xml_element="TIN gerado",
                blocking=False,
            )

        if policy == "BLOCK_PRODUCTION":
            return self._invalid(row, "NOT_COLLECTED", "US Tax ID ausente com politica de bloqueio.")
        if policy == "EMPTY_ELEMENT":
            return self._invalid(row, "NOT_COLLECTED", "TIN vazio nao e gerado porque o XSD FATCA exige tamanho minimo 1.")
        if policy == "OFFICIAL_MISSING_CODE":
            return self._invalid(row, "NOT_COLLECTED", "Nenhum codigo oficial de motivo foi configurado.")

        return FatcaTinDecision(
            tins=[],
            status=status or "NOT_COLLECTED",
            reason=reason or "US Tax ID ausente; aguardando confirmacao fiscal.",
            policy=policy,
            treatment="US Tax ID ausente; elemento TIN omitido conforme XSD FATCA permite minOccurs=0 em modo tecnico/omissao configurada.",
            xml_element="TIN omitido",
            blocking=False,
        )

    def should_block_generation(self, row: dict[str, Any], profile: MappingProfile) -> bool:
        return self.decide_xml_representation(row, profile).blocking

    def validate(self, row: dict[str, Any], profile: MappingProfile) -> ValidationIssue | None:
        return self.decide_xml_representation(row, profile).issue

    def get_reason_code(self, row: dict[str, Any], profile: MappingProfile) -> str:
        return self.decide_xml_representation(row, profile).reason

    def generate_audit_entry(self, row: dict[str, Any], profile: MappingProfile) -> dict[str, object]:
        decision = self.decide_xml_representation(row, profile)
        return {
            "linha_planilha": row.get("_excel_row") or "",
            "cliente_mascarado": mask_value(row.get("NomeCliente", "")),
            "documento_brasileiro_mascarado": mask_value(row.get("_documento_brasileiro") or row.get("DocumentoCliente", "")),
            "numero_conta_mascarado": mask_value(row.get("NumConta", "")),
            "classificacao_fatca": "FATCA",
            "us_tax_id_informado": "sim" if decision.tins else "nao",
            "status": decision.status,
            "motivo_ausencia": decision.reason,
            "tratamento_aplicado": decision.treatment,
            "elemento_omitido_ou_gerado": decision.xml_element,
            "resultado_validacao_xsd": "validar_apos_xml",
            "bloqueante_para_envio": "sim" if decision.blocking or decision.policy == TECHNICAL_TEST_POLICY else "nao",
            "data_hora": "",
        }

    def _invalid(self, row: dict[str, Any], status: str, message: str) -> FatcaTinDecision:
        issue = ValidationIssue("erro", "FATCA_TIN001", message, "fatca.us_tin", _excel_row(row), "Informe um US Tax ID valido ou altere a politica apos confirmacao fiscal.")
        return FatcaTinDecision([], status, message, DEFAULT_MISSING_US_TIN_POLICY, message, "TIN nao gerado", True, issue)

    def _invalid_us_tin_reason(self, row: dict[str, Any], value: str, issued_by: str) -> str:
        upper = value.upper()
        digits = digits_only(value)
        br_doc = digits_only(row.get("_documento_brasileiro") or row.get("DocumentoCliente", ""))
        account = digits_only(row.get("NumConta", ""))
        if upper in FORBIDDEN_PLACEHOLDERS or digits in {"0" * 9, "9" * 9}:
            return "US Tax ID possui valor ficticio ou marcador proibido."
        if issued_by != "US":
            return "US Tax ID informado deve ter pais emissor US."
        if br_doc and digits and digits == br_doc:
            return "CPF/CNPJ brasileiro nao pode ser usado como US Tax ID."
        if account and digits and digits == account:
            return "Numero da conta nao pode ser usado como US Tax ID."
        if digits in {"FI107442", "107442"}:
            return "FI Number da instituicao nao pode ser usado como US Tax ID do cliente."
        if digits and (validate_cpf(digits.zfill(11)) or validate_cnpj(digits.zfill(14))):
            return "Documento com formato de CPF/CNPJ nao pode ser classificado como US Tax ID."
        if not 1 <= len(value) <= 200:
            return "US Tax ID deve ter entre 1 e 200 caracteres."
        return ""


def _normalize_us_tin(value: Any) -> str:
    text = normalize_text(value)
    if text.upper() in FORBIDDEN_PLACEHOLDERS:
        return ""
    return "".join(char for char in text if char.isalnum() or char == "-")


def _normalize_policy(policy: str) -> str:
    aliases = {
        "BLOCK_GENERATION": "BLOCK_PRODUCTION",
        "OMIT_IF_SCHEMA_ALLOWS": "OMIT_ELEMENT",
        "GENERATE_EMPTY_IF_SCHEMA_ALLOWS": "EMPTY_ELEMENT",
        "USE_OFFICIAL_REASON_CODE": "OFFICIAL_MISSING_CODE",
        "PENDING_FISCAL_CONFIRMATION": TECHNICAL_TEST_POLICY,
    }
    return aliases.get(policy, policy)


def _profile_value(profile: MappingProfile, row: dict[str, Any], field: str, default: str) -> str:
    rule = profile.field_mappings.get(field)
    if not rule:
        return default
    if rule.source == "fixed":
        return normalize_text(rule.fixed_value) or default
    if rule.source == "column" and rule.column:
        return normalize_text(row.get(rule.column, "")) or default
    if rule.source == "empty":
        return ""
    return default


def _excel_row(row: dict[str, Any]) -> int | None:
    value = row.get("_excel_row")
    return int(value) if isinstance(value, int) else None
