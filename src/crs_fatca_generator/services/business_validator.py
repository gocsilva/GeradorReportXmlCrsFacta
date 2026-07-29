from __future__ import annotations

import re
from crs_fatca_generator.services.fatca_missing_tin_policy import FORBIDDEN_PLACEHOLDERS
from crs_fatca_generator.services.tax_identifier_service import digits_only, validate_cnpj, validate_cpf
from crs_fatca_generator.models.domain import TaxReport, ValidationIssue


class BusinessValidator:
    def validate(self, report: TaxReport, enums: dict[str, list[str]]) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if not report.message_spec.message_ref_id:
            issues.append(ValidationIssue("erro", "MSG001", "MessageRefId e obrigatorio.", "MessageRefId", suggestion="Mapeie uma coluna ou use valor automatico."))
        if report.kind == "crs":
            if report.message_spec.transmitting_country != "KY":
                issues.append(ValidationIssue("erro", "CRS003", "Neste perfil CRS, TransmittingCountry deve ser KY.", "TransmittingCountry"))
            if report.message_spec.receiving_country != "BR":
                issues.append(ValidationIssue("erro", "CRS004", "Neste perfil CRS, ReceivingCountry deve ser BR.", "ReceivingCountry"))
        if report.kind == "fatca":
            if report.message_spec.transmitting_country != "KY":
                issues.append(ValidationIssue("erro", "FATCA003", "Neste perfil FATCA, TransmittingCountry deve ser KY.", "TransmittingCountry"))
            if report.message_spec.receiving_country != "US":
                issues.append(ValidationIssue("erro", "FATCA004", "Neste perfil FATCA, ReceivingCountry deve ser US.", "ReceivingCountry"))
        if report.kind == "crs" and report.message_spec.message_type_indic not in enums.get("CrsMessageTypeIndic_EnumType", []):
            issues.append(ValidationIssue("erro", "CRS001", "MessageTypeIndic CRS invalido.", "MessageTypeIndic", suggestion="Use CRS701, CRS702 ou CRS703 conforme o XSD."))
        doc_ids: set[str] = set()
        if report.nil_report and report.accounts:
            issues.append(ValidationIssue("erro", "FATCA001", "NilReport e AccountReport sao mutuamente exclusivos.", "NilReport"))
        for account in report.accounts:
            if account.doc_spec.doc_ref_id in doc_ids:
                issues.append(ValidationIssue("erro", "DOC001", "DocRefId duplicado no arquivo.", "DocRefId", suggestion="Use geracao automatica ou informe identificadores unicos."))
            doc_ids.add(account.doc_spec.doc_ref_id)
            if account.account_holder is None:
                issues.append(ValidationIssue("erro", "ACC001", "AccountHolder e obrigatorio.", "AccountHolder"))
                continue
            if account.account_currency != "USD":
                issues.append(ValidationIssue("erro", "CUR001", "Neste perfil, a moeda dos saldos e pagamentos deve ser USD.", "AccountBalance/@currCode"))
            for payment in account.payments:
                if payment.currency != account.account_currency:
                    issues.append(ValidationIssue("erro", "CUR002", "Pagamento usa moeda diferente do saldo da conta.", "PaymentAmnt/@currCode"))
            holder = account.account_holder
            if holder.kind == "individual" and (not holder.name.first_name or not holder.name.last_name):
                issues.append(ValidationIssue("erro", "CHOICE001", "Titular individual exige FirstName e LastName.", "AccountHolder/Individual"))
            if holder.kind == "organisation" and not holder.name.organisation_name:
                issues.append(ValidationIssue("erro", "CHOICE002", "Titular organizacao exige Name.", "AccountHolder/Organisation"))
            if report.kind == "crs" and holder.kind == "organisation" and holder.acct_holder_type not in enums.get("CrsAcctHolderType_EnumType", []):
                issues.append(ValidationIssue("erro", "CRS002", "AcctHolderType CRS invalido.", "AcctHolderType"))
            if report.kind == "fatca" and holder.kind == "organisation" and holder.acct_holder_type not in enums.get("FatcaAcctHolderType_EnumType", []):
                issues.append(ValidationIssue("erro", "FATCA002", "AcctHolderType FATCA invalido.", "AcctHolderType"))
            if report.kind == "fatca":
                issues.extend(self._validate_fatca_us_tin(holder, account.account_number))
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", account.account_number):
                issues.append(ValidationIssue("erro", "SEC001", "Caracter de controle proibido no numero da conta.", "AccountNumber"))
        return issues

    def _validate_fatca_us_tin(self, holder: object, account_number: str) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if getattr(holder, "fatca_us_tin_blocking", "") == "sim":
            issues.append(ValidationIssue("erro", "FATCA_TIN001", getattr(holder, "fatca_us_tin_reason", "") or "US Tax ID pendente bloqueia a geracao.", "fatca.us_tin"))
        for tin in getattr(holder, "tins", []):
            value = str(tin.value or "")
            digits = digits_only(value)
            if tin.issued_by != "US":
                issues.append(ValidationIssue("erro", "FATCA_TIN002", "TIN FATCA de cliente deve usar issuedBy=US quando informado.", "sfa:TIN/@issuedBy"))
            if value.upper() in FORBIDDEN_PLACEHOLDERS or digits in {"0" * 9, "9" * 9}:
                issues.append(ValidationIssue("erro", "FATCA_TIN003", "TIN FATCA possui valor ficticio ou marcador proibido.", "sfa:TIN"))
            if digits and digits == digits_only(getattr(holder, "documento_brasileiro", "")):
                issues.append(ValidationIssue("erro", "FATCA_TIN004", "CPF/CNPJ brasileiro nao pode ser usado como US Tax ID.", "sfa:TIN"))
            if digits and digits == digits_only(account_number):
                issues.append(ValidationIssue("erro", "FATCA_TIN005", "Numero da conta nao pode ser usado como US Tax ID.", "sfa:TIN"))
            if digits and (validate_cpf(digits.zfill(11)) or validate_cnpj(digits.zfill(14))):
                issues.append(ValidationIssue("erro", "FATCA_TIN006", "Documento com formato de CPF/CNPJ nao pode ser usado como US Tax ID.", "sfa:TIN"))
        return issues
