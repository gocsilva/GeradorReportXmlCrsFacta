from __future__ import annotations

import logging
from pathlib import Path

from lxml import etree

from crs_fatca_generator.models.domain import AccountReport, Address, DocSpec, Party, Payment, TaxReport
from .xml_helpers import CRS_CFC_NS, CRS_FTCA_V1_NS, CRS_ISO_NS, CRS_NS, CRS_STF_NS, XSI_NS, add, atomic_write, q


logger = logging.getLogger(__name__)


class CrsGenerator:
    def build_tree(self, report: TaxReport, schema_location: str = "CrsXML_v3.0.xsd") -> etree._ElementTree:
        root = etree.Element(
            q(CRS_NS, "CRS_OECD"),
            nsmap={None: CRS_NS, "stf": CRS_STF_NS, "cfc": CRS_CFC_NS, "iso": CRS_ISO_NS, "ftc": CRS_FTCA_V1_NS, "xsi": XSI_NS},
            attrib={q(XSI_NS, "schemaLocation"): f"{CRS_NS} {schema_location}", "version": "3.0"},
        )
        self._message_spec(root, report)
        body = add(root, CRS_NS, "CrsBody")
        self._reporting_fi(body, report)
        group = add(body, CRS_NS, "ReportingGroup")
        for account in report.accounts:
            self._account(group, account)
        return etree.ElementTree(root)

    def write(self, report: TaxReport, output_path: Path, pretty_print: bool = True) -> etree._ElementTree:
        tree = self.build_tree(report)
        atomic_write(tree, output_path, pretty_print)
        return tree

    def _message_spec(self, root: etree._Element, report: TaxReport) -> None:
        msg = add(root, CRS_NS, "MessageSpec")
        spec = report.message_spec
        if spec.sending_company_in:
            add(msg, CRS_NS, "SendingCompanyIN", spec.sending_company_in)
        add(msg, CRS_NS, "TransmittingCountry", spec.transmitting_country)
        add(msg, CRS_NS, "ReceivingCountry", spec.receiving_country)
        add(msg, CRS_NS, "MessageType", "CRS")
        if spec.warning:
            add(msg, CRS_NS, "Warning", spec.warning)
        if spec.contact:
            add(msg, CRS_NS, "Contact", spec.contact)
        add(msg, CRS_NS, "MessageRefId", spec.message_ref_id)
        add(msg, CRS_NS, "MessageTypeIndic", spec.message_type_indic or "CRS701")
        for corr in spec.corr_message_ref_ids:
            add(msg, CRS_NS, "CorrMessageRefId", corr)
        add(msg, CRS_NS, "ReportingPeriod", spec.reporting_period)
        add(msg, CRS_NS, "Timestamp", spec.timestamp)

    def _reporting_fi(self, parent: etree._Element, report: TaxReport) -> None:
        fi = add(parent, CRS_NS, "ReportingFI")
        self._organisation_party(fi, report.reporting_fi.party, CRS_NS, CRS_CFC_NS, tax_id_element="IN")
        self._doc_spec(fi, report.reporting_fi.doc_spec, CRS_NS, CRS_STF_NS)

    def _account(self, parent: etree._Element, account: AccountReport) -> None:
        item = add(parent, CRS_NS, "AccountReport")
        self._doc_spec(item, account.doc_spec, CRS_NS, CRS_STF_NS)
        attrs: dict[str, str] = {}
        if account.account_number_type:
            attrs["AcctNumberType"] = account.account_number_type
        if account.undocumented_account:
            attrs["UndocumentedAccount"] = account.undocumented_account
        if account.closed_account:
            attrs["ClosedAccount"] = account.closed_account
        if account.dormant_account:
            attrs["DormantAccount"] = account.dormant_account
        add(item, CRS_NS, "AccountNumber", account.account_number, attrs)
        holder = add(item, CRS_NS, "AccountHolder")
        if account.account_holder:
            for equity in account.account_holder.crs_equity_interest_types:
                add(holder, CRS_NS, "EquityInterestType", equity)
            add(holder, CRS_NS, "SelfCert", account.account_holder.crs_self_cert or "CRS901")
            if account.account_holder.kind == "organisation":
                org = add(holder, CRS_NS, "Organisation")
                self._organisation_party(org, account.account_holder, CRS_NS, CRS_CFC_NS, tax_id_element="TIN")
                add(holder, CRS_NS, "AcctHolderType", account.account_holder.acct_holder_type or "CRS101")
            else:
                ind = add(holder, CRS_NS, "Individual")
                self._person_party(ind, account.account_holder, CRS_NS, CRS_CFC_NS)
        for controlling in account.controlling_persons:
            cp = add(item, CRS_NS, "ControllingPerson")
            ind = add(cp, CRS_NS, "Individual")
            self._person_party(ind, controlling, CRS_NS, CRS_CFC_NS)
            for cp_type in controlling.crs_controlling_person_types or ["CRS801"]:
                add(cp, CRS_NS, "CtrlgPersonType", cp_type)
            add(cp, CRS_NS, "SelfCert", controlling.crs_controlling_self_cert or "CRS1001")
        add(item, CRS_NS, "AccountBalance", account.account_balance, {"currCode": account.account_currency})
        for payment in account.payments:
            self._payment(item, payment)
        add(item, CRS_NS, "DDProcedure", account.crs_dd_procedure or "CRS1201")
        add(item, CRS_NS, "AccountType", account.crs_account_type or "CRS1101")
        if account.crs_joint_account_number:
            joint = add(item, CRS_NS, "JointAccount")
            add(joint, CRS_NS, "Number", account.crs_joint_account_number)

    def _doc_spec(self, parent: etree._Element, doc: DocSpec, doc_ns: str, child_ns: str) -> None:
        elem = add(parent, doc_ns, "DocSpec")
        add(elem, child_ns, "DocTypeIndic", doc.doc_type_indic)
        add(elem, child_ns, "DocRefId", doc.doc_ref_id)
        if doc.corr_message_ref_id:
            add(elem, child_ns, "CorrMessageRefId", doc.corr_message_ref_id)
        if doc.corr_doc_ref_id:
            add(elem, child_ns, "CorrDocRefId", doc.corr_doc_ref_id)

    def _organisation_party(self, parent: etree._Element, party: Party, party_ns: str, address_child_ns: str, tax_id_element: str = "IN") -> None:
        for country in party.res_country_codes:
            add(parent, party_ns, "ResCountryCode", country)
        for tin in party.tins:
            attrs = {"issuedBy": tin.issued_by} if tin.issued_by else {}
            logger.info(
                "TRACE_BUTTON_PIPELINE CrsGenerator._organisation_party element=%s issuedBy=%s holder_kind=%s",
                tax_id_element,
                tin.issued_by,
                party.kind,
            )
            add(parent, party_ns, tax_id_element, tin.value, attrs)
        add(parent, party_ns, "Name", party.name.organisation_name or "Organizacao")
        address = add(parent, party_ns, "Address")
        self._address(address, party.address, address_child_ns)

    def _person_party(self, parent: etree._Element, party: Party, party_ns: str, address_child_ns: str) -> None:
        for country in party.res_country_codes:
            add(parent, party_ns, "ResCountryCode", country)
        for tin in party.tins:
            attrs = {"issuedBy": tin.issued_by} if tin.issued_by else {}
            add(parent, party_ns, "TIN", tin.value, attrs)
        name = add(parent, party_ns, "Name")
        add(name, party_ns, "FirstName", party.name.first_name or "Nome")
        add(name, party_ns, "LastName", party.name.last_name or "Sobrenome")
        address = add(parent, party_ns, "Address")
        self._address(address, party.address, address_child_ns)
        if party.birth_date:
            birth = add(parent, party_ns, "BirthInfo")
            add(birth, party_ns, "BirthDate", party.birth_date)

    def _address(self, parent: etree._Element, address: Address, child_ns: str) -> None:
        if address.legal_address_type:
            parent.set("legalAddressType", address.legal_address_type)
        add(parent, child_ns, "CountryCode", address.country_code)
        add(parent, child_ns, "AddressFree", address.address_free)

    def _payment(self, parent: etree._Element, payment: Payment) -> None:
        elem = add(parent, CRS_NS, "Payment")
        add(elem, CRS_NS, "Type", payment.payment_type)
        add(elem, CRS_NS, "PaymentAmnt", payment.amount, {"currCode": payment.currency})
