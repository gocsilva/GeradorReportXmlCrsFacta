from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Callable

from lxml import etree

from crs_fatca_generator.models.domain import AccountReport, MessageSpec, TaxReport
from crs_fatca_generator.services.crs_generator import CrsGenerator
from crs_fatca_generator.services.fatca_generator import FatcaGenerator
from crs_fatca_generator.services.xml_helpers import atomic_write


ProgressCallback = Callable[[int, int, str], None]
DITC_CRS_MAX_MB = 150
SPLIT_SIZE_SAMPLE_ACCOUNTS = 128
SPLIT_HEADER_SAFETY_BYTES = 4 * 1024


class XmlSplitterService:
    def write_report_parts(
        self,
        kind: str,
        report: TaxReport,
        output_path: Path,
        pretty_print: bool = True,
        size_limit_mb: int = 0,
        progress_callback: ProgressCallback | None = None,
        write_progress_callback: Callable[[int, int, AccountReport], None] | None = None,
    ) -> list[tuple[Path, etree._ElementTree]]:
        generator = CrsGenerator() if kind == "crs" else FatcaGenerator()
        if size_limit_mb <= 0 or not report.accounts or report.nil_report:
            tree = generator.write(report, output_path, pretty_print, progress_callback=write_progress_callback)
            self._emit(progress_callback, 1, 1, output_path.name)
            return [(output_path, tree)]

        part_specs = self._plan_report_parts(kind, report, size_limit_mb, pretty_print, write_progress_callback)
        if len(part_specs) <= 1 and part_specs[0][0] == report.message_spec.receiving_country:
            tree = part_specs[0][2] or generator.build_tree(report)
            self._emit(progress_callback, 1, 1, output_path.name)
            atomic_write(tree, output_path, pretty_print)
            return [(output_path, tree)]

        written: list[tuple[Path, etree._ElementTree]] = []
        total = len(part_specs)
        for index, (country, accounts, tree) in enumerate(part_specs, 1):
            part_path = _country_part_path(output_path, country, index, total)
            part_report = self._part_report(report, accounts, country, index)
            if tree is None:
                tree = generator.build_tree(part_report)
            else:
                _set_tree_message_ref_id(tree, part_report.message_spec.message_ref_id)
            atomic_write(tree, part_path, pretty_print)
            written.append((part_path, tree))
            self._emit(progress_callback, index, total, part_path.name)
        return written

    def split_existing_xml(
        self,
        xml_path: Path,
        output_dir: Path,
        size_limit_mb: int,
        progress_callback: ProgressCallback | None = None,
    ) -> list[Path]:
        if size_limit_mb <= 0:
            raise ValueError("Informe um limite maior que 0 MB para dividir um XML existente.")
        parser = etree.XMLParser(remove_blank_text=True)
        tree = etree.parse(str(xml_path), parser)
        root = tree.getroot()
        group = _find_reporting_group(root)
        if group is None:
            raise ValueError("ReportingGroup nao encontrado no XML.")
        accounts = [deepcopy(item) for item in group if etree.QName(item).localname == "AccountReport"]
        if not accounts:
            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / _part_path(xml_path, 1).name
            atomic_write(tree, target, True)
            self._emit(progress_callback, 1, 1, target.name)
            return [target]

        kind = _xml_kind(root)
        chunk_specs: list[tuple[str, list[etree._Element]]] = []
        for country, country_accounts in _existing_accounts_by_receiving_country(kind, root, accounts):
            for chunk in self._chunk_existing_accounts(root, country_accounts, size_limit_mb):
                chunk_specs.append((country, chunk))
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        total = len(chunk_specs)
        for index, (country, chunk) in enumerate(chunk_specs, 1):
            part_root = deepcopy(root)
            self._set_existing_message_ref_id(part_root, index)
            self._set_existing_receiving_country(part_root, country)
            part_group = _find_reporting_group(part_root)
            if part_group is None:
                raise ValueError("ReportingGroup nao encontrado ao criar parte.")
            for child in list(part_group):
                if etree.QName(child).localname in {"AccountReport", "NilReport"}:
                    part_group.remove(child)
            for account in chunk:
                part_group.append(deepcopy(account))
            target = output_dir / _country_part_path(xml_path, country, index, total).name
            atomic_write(etree.ElementTree(part_root), target, True)
            paths.append(target)
            self._emit(progress_callback, index, total, target.name)
        return paths

    def _plan_report_parts(
        self,
        kind: str,
        report: TaxReport,
        size_limit_mb: int,
        pretty_print: bool,
        write_progress_callback: Callable[[int, int, AccountReport], None] | None = None,
    ) -> list[tuple[str, list[AccountReport], etree._ElementTree | None]]:
        generator = CrsGenerator() if kind == "crs" else FatcaGenerator()
        max_bytes = max(_mb_to_bytes(size_limit_mb) - SPLIT_HEADER_SAFETY_BYTES, 1)
        planned: list[tuple[str, list[AccountReport], etree._ElementTree | None]] = []
        country_groups = _accounts_by_receiving_country(kind, report)
        for country, accounts in country_groups:
            planned.extend(self._plan_country_parts(report, country, accounts, max_bytes, pretty_print, generator, write_progress_callback))
        return planned

    def _plan_country_parts(
        self,
        report: TaxReport,
        country: str,
        accounts: list[AccountReport],
        max_bytes: int,
        pretty_print: bool,
        generator: object,
        write_progress_callback: Callable[[int, int, AccountReport], None] | None = None,
    ) -> list[tuple[str, list[AccountReport], etree._ElementTree | None]]:
        planned: list[tuple[str, list[AccountReport], etree._ElementTree | None]] = []
        start = 0
        total = len(accounts)
        if write_progress_callback and accounts:
            write_progress_callback(1, total, accounts[0])
        while start < total:
            chunk_accounts, tree = self._largest_fitting_chunk(report, country, accounts, start, max_bytes, pretty_print, generator)
            planned.append((country, chunk_accounts, tree))
            start += len(chunk_accounts)
            if write_progress_callback and chunk_accounts:
                write_progress_callback(start, total, chunk_accounts[-1])
        return planned

    def _largest_fitting_chunk(
        self,
        report: TaxReport,
        country: str,
        accounts: list[AccountReport],
        start: int,
        max_bytes: int,
        pretty_print: bool,
        generator: object,
    ) -> tuple[list[AccountReport], etree._ElementTree]:
        remaining = len(accounts) - start
        good_count = 0
        good_tree: etree._ElementTree | None = None
        measured: dict[int, tuple[int, etree._ElementTree]] = {}

        def measure(count: int) -> tuple[int, etree._ElementTree]:
            count = max(min(count, remaining), 1)
            if count in measured:
                return measured[count]
            part_accounts = accounts[start : start + count]
            part_report = self._part_report(report, part_accounts, country, 0)
            tree = generator.build_tree(part_report)  # type: ignore[attr-defined]
            measured[count] = (_tree_size(tree, pretty_print), tree)
            return measured[count]

        sample_count = min(SPLIT_SIZE_SAMPLE_ACCOUNTS, remaining)
        sample_size, sample_tree = measure(sample_count)
        if sample_size <= max_bytes:
            estimated_count = int(sample_count * (max_bytes / max(sample_size, 1)) * 0.95)
            initial_count = min(max(estimated_count, sample_count), remaining)
        else:
            initial_count = sample_count

        size, tree = measure(initial_count)
        if size <= max_bytes:
            good_count = initial_count
            good_tree = tree
            low = initial_count + 1
            high = remaining
            probe = initial_count
            while probe < remaining:
                probe = min(probe * 2, remaining)
                size, tree = measure(probe)
                if size <= max_bytes:
                    good_count = probe
                    good_tree = tree
                    low = probe + 1
                    if probe == remaining:
                        break
                    continue
                high = probe - 1
                break
        else:
            low = 1
            high = initial_count - 1
            if sample_count == 1:
                good_tree = sample_tree

        while low <= high:
            middle = (low + high) // 2
            size, tree = measure(middle)
            if size <= max_bytes:
                good_count = middle
                good_tree = tree
                low = middle + 1
            else:
                high = middle - 1

        if good_count <= 0 or good_tree is None:
            _size, good_tree = measure(1)
            good_count = 1
        return accounts[start : start + good_count], good_tree

    def _part_report(self, report: TaxReport, accounts: list[AccountReport], country: str, part_index: int) -> TaxReport:
        message = _part_message_spec(report.message_spec, country, part_index)
        return replace(report, message_spec=message, accounts=accounts)

    def _chunk_existing_accounts(
        self,
        root: etree._Element,
        accounts: list[etree._Element],
        size_limit_mb: int,
    ) -> list[list[etree._Element]]:
        max_bytes = max(_mb_to_bytes(size_limit_mb) - SPLIT_HEADER_SAFETY_BYTES, 1)
        empty_root = deepcopy(root)
        group = _find_reporting_group(empty_root)
        if group is None:
            raise ValueError("ReportingGroup nao encontrado.")
        for child in list(group):
            if etree.QName(child).localname in {"AccountReport", "NilReport"}:
                group.remove(child)
        base_size = _tree_size(etree.ElementTree(empty_root), True)
        chunks: list[list[etree._Element]] = []
        current: list[etree._Element] = []
        current_size = base_size
        for account in accounts:
            account_size = len(etree.tostring(account, encoding="UTF-8", xml_declaration=False))
            if current and current_size + account_size > max_bytes:
                chunks.append(current)
                current = []
                current_size = base_size
            current.append(account)
            current_size += account_size
        if current:
            chunks.append(current)
        return chunks

    def _set_existing_message_ref_id(self, root: etree._Element, part_index: int) -> None:
        matches = root.xpath(".//*[local-name()='MessageRefId']")
        if not matches:
            return
        current = str(matches[0].text or "").strip() or "MESSAGE"
        matches[0].text = f"{_clean_identifier(current)}P{part_index:03d}"

    def _set_existing_receiving_country(self, root: etree._Element, country: str) -> None:
        matches = root.xpath(".//*[local-name()='ReceivingCountry']")
        if matches:
            matches[0].text = country

    def _emit(self, progress_callback: ProgressCallback | None, processed: int, total: int, name: str) -> None:
        if progress_callback:
            progress_callback(processed, total, name)


def _find_reporting_group(root: etree._Element) -> etree._Element | None:
    matches = root.xpath(".//*[local-name()='ReportingGroup']")
    return matches[0] if matches else None


def _tree_size(tree: etree._ElementTree, pretty_print: bool) -> int:
    return len(etree.tostring(tree, encoding="UTF-8", xml_declaration=True, pretty_print=pretty_print))


def _mb_to_bytes(value: int) -> int:
    return max(int(value), 0) * 1024 * 1024


def _part_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.stem}_parte{index:03d}{path.suffix or '.xml'}")


def _country_part_path(path: Path, country: str, index: int, total: int) -> Path:
    country_suffix = _clean_identifier(country)[:2] or "XX"
    if total <= 1:
        return path
    return path.with_name(f"{path.stem}_{country_suffix}_parte{index:03d}{path.suffix or '.xml'}")


def _accounts_by_receiving_country(kind: str, report: TaxReport) -> list[tuple[str, list[AccountReport]]]:
    if kind != "crs":
        return [(report.message_spec.receiving_country, report.accounts)]
    groups: dict[str, list[AccountReport]] = {}
    for account in report.accounts:
        country = _account_receiving_country(account, report.message_spec.receiving_country)
        groups.setdefault(country, []).append(account)
    return sorted(groups.items(), key=lambda item: item[0])


def _account_receiving_country(account: AccountReport, default: str) -> str:
    holder = account.account_holder
    if holder and holder.res_country_codes:
        return _clean_identifier(holder.res_country_codes[0])[:2] or default
    return default


def _existing_accounts_by_receiving_country(
    kind: str,
    root: etree._Element,
    accounts: list[etree._Element],
) -> list[tuple[str, list[etree._Element]]]:
    default = _existing_receiving_country(root)
    if kind != "crs":
        return [(default, accounts)]
    groups: dict[str, list[etree._Element]] = {}
    for account in accounts:
        country = _existing_account_receiving_country(account, default)
        groups.setdefault(country, []).append(account)
    return sorted(groups.items(), key=lambda item: item[0])


def _existing_receiving_country(root: etree._Element) -> str:
    matches = root.xpath(".//*[local-name()='ReceivingCountry']")
    return _clean_identifier(matches[0].text if matches else "")[:2] or "BR"


def _existing_account_receiving_country(account: etree._Element, default: str) -> str:
    matches = account.xpath("./*[local-name()='AccountHolder']/*[local-name()='Organisation' or local-name()='Individual']/*[local-name()='ResCountryCode']")
    return _clean_identifier(matches[0].text if matches else "")[:2] or default


def _xml_kind(root: etree._Element) -> str:
    local_name = etree.QName(root).localname.lower()
    if "fatca" in local_name:
        return "fatca"
    return "crs"


def _part_message_spec(message: MessageSpec, country: str, part_index: int) -> MessageSpec:
    suffix = f"{_clean_identifier(country)[:2] or 'XX'}P{part_index:03d}" if part_index else ""
    return replace(
        message,
        receiving_country=country,
        message_ref_id=f"{_clean_identifier(message.message_ref_id)}{suffix}" if suffix else message.message_ref_id,
    )


def _set_tree_message_ref_id(tree: etree._ElementTree, value: str) -> None:
    matches = tree.getroot().xpath(".//*[local-name()='MessageRefId']")
    if matches:
        matches[0].text = value


def _clean_identifier(value: str) -> str:
    return "".join(char for char in str(value or "") if char.isalnum())
