from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from lxml import etree

from crs_fatca_generator.models.domain import AccountReport, TaxReport
from crs_fatca_generator.services.crs_generator import CrsGenerator
from crs_fatca_generator.services.fatca_generator import FatcaGenerator
from crs_fatca_generator.services.xml_helpers import CRS_NS, FATCA_NS, atomic_write


ProgressCallback = Callable[[int, int, str], None]


class XmlSplitterService:
    def write_report_parts(
        self,
        kind: str,
        report: TaxReport,
        output_path: Path,
        pretty_print: bool = True,
        size_limit_mb: int = 0,
        progress_callback: ProgressCallback | None = None,
    ) -> list[tuple[Path, etree._ElementTree]]:
        generator = CrsGenerator() if kind == "crs" else FatcaGenerator()
        if size_limit_mb <= 0 or not report.accounts or report.nil_report:
            tree = generator.write(report, output_path, pretty_print)
            self._emit(progress_callback, 1, 1, output_path.name)
            return [(output_path, tree)]

        chunks = self._chunk_report_accounts(kind, report, size_limit_mb, pretty_print)
        if len(chunks) <= 1:
            tree = generator.write(report, output_path, pretty_print)
            self._emit(progress_callback, 1, 1, output_path.name)
            return [(output_path, tree)]

        written: list[tuple[Path, etree._ElementTree]] = []
        total = len(chunks)
        for index, accounts in enumerate(chunks, 1):
            part_path = _part_path(output_path, index)
            part_report = replace(report, accounts=accounts)
            tree = generator.write(part_report, part_path, pretty_print)
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

        chunks = self._chunk_existing_accounts(root, accounts, size_limit_mb)
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        total = len(chunks)
        for index, chunk in enumerate(chunks, 1):
            part_root = deepcopy(root)
            part_group = _find_reporting_group(part_root)
            if part_group is None:
                raise ValueError("ReportingGroup nao encontrado ao criar parte.")
            for child in list(part_group):
                if etree.QName(child).localname in {"AccountReport", "NilReport"}:
                    part_group.remove(child)
            for account in chunk:
                part_group.append(deepcopy(account))
            target = output_dir / _part_path(xml_path, index).name
            atomic_write(etree.ElementTree(part_root), target, True)
            paths.append(target)
            self._emit(progress_callback, index, total, target.name)
        return paths

    def _chunk_report_accounts(
        self,
        kind: str,
        report: TaxReport,
        size_limit_mb: int,
        pretty_print: bool,
    ) -> list[list[AccountReport]]:
        generator = CrsGenerator() if kind == "crs" else FatcaGenerator()
        max_bytes = _mb_to_bytes(size_limit_mb)
        base_report = replace(report, accounts=[])
        base_size = _tree_size(generator.build_tree(base_report), pretty_print)
        chunks: list[list[AccountReport]] = []
        current: list[AccountReport] = []
        current_size = base_size
        for account in report.accounts:
            account_size = self._account_size(kind, generator, account)
            if current and current_size + account_size > max_bytes:
                chunks.append(current)
                current = []
                current_size = base_size
            current.append(account)
            current_size += account_size
        if current:
            chunks.append(current)
        return chunks

    def _chunk_existing_accounts(
        self,
        root: etree._Element,
        accounts: list[etree._Element],
        size_limit_mb: int,
    ) -> list[list[etree._Element]]:
        max_bytes = _mb_to_bytes(size_limit_mb)
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

    def _account_size(self, kind: str, generator: object, account: AccountReport) -> int:
        namespace = CRS_NS if kind == "crs" else FATCA_NS
        parent = etree.Element(f"{{{namespace}}}ReportingGroup")
        generator._account(parent, account)  # type: ignore[attr-defined]
        return len(etree.tostring(parent[0], encoding="UTF-8", xml_declaration=False))

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
