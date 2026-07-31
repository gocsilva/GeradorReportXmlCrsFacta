from __future__ import annotations

from pathlib import Path
from typing import Callable

from lxml import etree

from crs_fatca_generator.models.domain import AccountReport, Address, DocSpec, Party, Payment, TaxReport
from .xml_helpers import FATCA_ISO_NS, FATCA_NS, FATCA_SFA_NS, FATCA_STF_NS, XSI_NS, add, atomic_write, q


class FatcaGenerator:
    def build_tree(
        self,
        report: TaxReport,
        schema_location: str = "FatcaXML_v2.0.1.xsd",
        progress_callback: Callable[[int, int, AccountReport], None] | None = None,
    ) -> etree._ElementTree:
        root = etree.Element(
            q(FATCA_NS, "FATCA_OECD"),
            nsmap={"ftc": FATCA_NS, "sfa": FATCA_SFA_NS, "stf": FATCA_STF_NS, "iso": FATCA_ISO_NS, "xsi": XSI_NS},
            attrib={q(XSI_NS, "schemaLocation"): f"{FATCA_NS} {schema_location}", "version": "2.0"},
        )
        self._message_spec(root, report)
        body = add(root, FATCA_NS, "FATCA")
        self._reporting_fi(body, report)
        group = add(body, FATCA_NS, "ReportingGroup")
        if report.nil_report:
            nil = add(group, FATCA_NS, "NilReport")
            self._doc_spec(nil, report.nil_report)
            add(nil, FATCA_NS, "NoAccountToReport", "yes")
        else:
            total = len(report.accounts)
            for index, account in enumerate(report.accounts, 1):
                if progress_callback and (index == 1 or index % 50 == 0 or index == total):
                    progress_callback(index, total, account)
                self._account(group, account)
        return etree.ElementTree(root)

    def write(
        self,
        report: TaxReport,
        output_path: Path,
        pretty_print: bool = True,
        progress_callback: Callable[[int, int, AccountReport], None] | None = None,
    ) -> etree._ElementTree:
        tree = self.build_tree(report, progress_callback=progress_callback)
        atomic_write(tree, output_path, pretty_print)
        return tree

    def _message_spec(self, root: etree._Element, report: TaxReport) -> None:
        msg = add(root, FATCA_NS, "MessageSpec")
        spec = report.message_spec
        if spec.sending_company_in:
            add(msg, FATCA_SFA_NS, "SendingCompanyIN", spec.sending_company_in)
        add(msg, FATCA_SFA_NS, "TransmittingCountry", spec.transmitting_country)
        add(msg, FATCA_SFA_NS, "ReceivingCountry", spec.receiving_country)
        add(msg, FATCA_SFA_NS, "MessageType", "FATCA")
        if spec.warning:
            add(msg, FATCA_SFA_NS, "Warning", spec.warning)
        if spec.contact:
            add(msg, FATCA_SFA_NS, "Contact", spec.contact)
        add(msg, FATCA_SFA_NS, "MessageRefId", spec.message_ref_id)
        for corr in spec.corr_message_ref_ids:
            add(msg, FATCA_SFA_NS, "CorrMessageRefId", corr)
        add(msg, FATCA_SFA_NS, "ReportingPeriod", spec.reporting_period)
        add(msg, FATCA_SFA_NS, "Timestamp", spec.timestamp)

    def _reporting_fi(self, parent: etree._Element, report: TaxReport) -> None:
        fi = add(parent, FATCA_NS, "ReportingFI")
        self._organisation_party(fi, report.reporting_fi.party)
        if report.reporting_fi.filer_category:
            add(fi, FATCA_NS, "FilerCategory", report.reporting_fi.filer_category)
        self._doc_spec(fi, report.reporting_fi.doc_spec)

    def _account(self, parent: etree._Element, account: AccountReport) -> None:
        item = add(parent, FATCA_NS, "AccountReport")
        self._doc_spec(item, account.doc_spec)
        attrs = {"AcctNumberType": account.account_number_type} if account.account_number_type else {}
        add(item, FATCA_NS, "AccountNumber", account.account_number, attrs)
        if account.closed_account:
            add(item, FATCA_NS, "AccountClosed", account.closed_account)
        holder = add(item, FATCA_NS, "AccountHolder")
        if account.account_holder:
            if account.account_holder.kind == "organisation":
                org = add(holder, FATCA_NS, "Organisation")
                self._organisation_party(org, account.account_holder)
                add(holder, FATCA_NS, "AcctHolderType", account.account_holder.acct_holder_type or "FATCA101")
            else:
                ind = add(holder, FATCA_NS, "Individual")
                self._person_party(ind, account.account_holder)
        for owner in account.substantial_owners:
            so = add(item, FATCA_NS, "SubstantialOwner")
            if owner.kind == "organisation":
                org = add(so, FATCA_NS, "Organisation")
                self._organisation_party(org, owner)
            else:
                ind = add(so, FATCA_NS, "Individual")
                self._person_party(ind, owner)
        add(item, FATCA_NS, "AccountBalance", account.account_balance, {"currCode": account.account_currency})
        for payment in account.payments:
            self._payment(item, payment)

    def _doc_spec(self, parent: etree._Element, doc: DocSpec) -> None:
        elem = add(parent, FATCA_NS, "DocSpec")
        add(elem, FATCA_NS, "DocTypeIndic", doc.doc_type_indic)
        add(elem, FATCA_NS, "DocRefId", doc.doc_ref_id)
        if doc.corr_message_ref_id:
            add(elem, FATCA_NS, "CorrMessageRefId", doc.corr_message_ref_id)
        if doc.corr_doc_ref_id:
            add(elem, FATCA_NS, "CorrDocRefId", doc.corr_doc_ref_id)

    def _organisation_party(self, parent: etree._Element, party: Party) -> None:
        for country in party.res_country_codes:
            add(parent, FATCA_SFA_NS, "ResCountryCode", country)
        for tin in party.tins:
            attrs = {"issuedBy": tin.issued_by} if tin.issued_by else {}
            add(parent, FATCA_SFA_NS, "TIN", tin.value, attrs)
        add(parent, FATCA_SFA_NS, "Name", party.name.organisation_name or "Organizacao")
        address = add(parent, FATCA_SFA_NS, "Address")
        self._address(address, party.address)

    def _person_party(self, parent: etree._Element, party: Party) -> None:
        for country in party.res_country_codes:
            add(parent, FATCA_SFA_NS, "ResCountryCode", country)
        for tin in party.tins:
            attrs = {"issuedBy": tin.issued_by} if tin.issued_by else {}
            add(parent, FATCA_SFA_NS, "TIN", tin.value, attrs)
        name = add(parent, FATCA_SFA_NS, "Name")
        add(name, FATCA_SFA_NS, "FirstName", party.name.first_name or "Nome")
        add(name, FATCA_SFA_NS, "LastName", party.name.last_name or "Sobrenome")
        address = add(parent, FATCA_SFA_NS, "Address")
        self._address(address, party.address)
        if party.birth_date:
            birth = add(parent, FATCA_SFA_NS, "BirthInfo")
            add(birth, FATCA_SFA_NS, "BirthDate", party.birth_date)

    def _address(self, parent: etree._Element, address: Address) -> None:
        if address.legal_address_type:
            parent.set("legalAddressType", address.legal_address_type)
        add(parent, FATCA_SFA_NS, "CountryCode", address.country_code)
        if address.legal_address_type:
            address_fix = add(parent, FATCA_SFA_NS, "AddressFix")
            add(address_fix, FATCA_SFA_NS, "City", _city_from_address(address.address_free))
            return
        add(parent, FATCA_SFA_NS, "AddressFree", address.address_free)

    def _payment(self, parent: etree._Element, payment: Payment) -> None:
        elem = add(parent, FATCA_NS, "Payment")
        add(elem, FATCA_NS, "Type", payment.payment_type)
        if payment.description:
            add(elem, FATCA_NS, "PaymentTypeDesc", payment.description)
        add(elem, FATCA_NS, "PaymentAmnt", payment.amount, {"currCode": payment.currency})


def _city_from_address(value: str) -> str:
    parts = [part.strip() for part in str(value or "").split(",") if part.strip()]
    return parts[-1] if parts else "George Town"
