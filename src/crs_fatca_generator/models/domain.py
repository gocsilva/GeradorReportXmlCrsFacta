from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationIssue:
    level: str
    code: str
    message: str
    field: str = ""
    excel_row: int | None = None
    suggestion: str = ""


@dataclass
class Name:
    first_name: str = ""
    last_name: str = ""
    organisation_name: str = ""
    name_type: str = ""


@dataclass
class Address:
    country_code: str
    address_free: str
    legal_address_type: str = ""


@dataclass
class TIN:
    value: str
    issued_by: str = ""


@dataclass
class DocSpec:
    doc_type_indic: str
    doc_ref_id: str
    corr_message_ref_id: str = ""
    corr_doc_ref_id: str = ""


@dataclass
class Party:
    kind: str
    res_country_codes: list[str]
    name: Name
    address: Address
    tins: list[TIN] = field(default_factory=list)
    documento_brasileiro: str = ""
    tipo_documento_brasileiro: str = ""
    cpf: str = ""
    cnpj: str = ""
    fatca_us_tin: str = ""
    fatca_us_tin_status: str = ""
    fatca_us_tin_reason: str = ""
    fatca_us_tin_issued_by: str = ""
    fatca_us_tin_policy: str = ""
    fatca_us_tin_blocking: str = ""
    birth_date: str = ""
    acct_holder_type: str = ""
    crs_self_cert: str = "CRS901"
    crs_equity_interest_types: list[str] = field(default_factory=list)
    crs_controlling_person_types: list[str] = field(default_factory=list)
    crs_controlling_self_cert: str = "CRS1001"
    fatca_filer_category: str = ""


@dataclass
class Payment:
    payment_type: str
    amount: str
    currency: str
    description: str = ""


@dataclass
class AccountReport:
    doc_spec: DocSpec
    account_number: str
    account_number_type: str
    closed_account: str = ""
    undocumented_account: str = ""
    dormant_account: str = ""
    account_holder: Party | None = None
    controlling_persons: list[Party] = field(default_factory=list)
    substantial_owners: list[Party] = field(default_factory=list)
    account_balance: str = "0.00"
    account_currency: str = "USD"
    payments: list[Payment] = field(default_factory=list)
    crs_dd_procedure: str = "CRS1201"
    crs_account_type: str = "CRS1101"
    crs_joint_account_number: str = ""


@dataclass
class ReportingFI:
    party: Party
    doc_spec: DocSpec
    filer_category: str = ""


@dataclass
class MessageSpec:
    sending_company_in: str
    transmitting_country: str
    receiving_country: str
    message_type: str
    message_ref_id: str
    reporting_period: str
    timestamp: str
    message_type_indic: str = ""
    corr_message_ref_ids: list[str] = field(default_factory=list)
    warning: str = ""
    contact: str = ""


@dataclass
class TaxReport:
    kind: str
    message_spec: MessageSpec
    reporting_fi: ReportingFI
    accounts: list[AccountReport] = field(default_factory=list)
    nil_report: DocSpec | None = None


@dataclass
class GenerationResult:
    kind: str
    xml_path: str
    valid: bool
    issues: list[ValidationIssue]
    summary: dict[str, int | str]
