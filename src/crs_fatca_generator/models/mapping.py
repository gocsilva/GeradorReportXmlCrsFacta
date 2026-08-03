from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SourceType = Literal["column", "fixed", "auto", "calculated", "empty"]


@dataclass
class MappingRule:
    source: SourceType = "empty"
    column: str = ""
    fixed_value: str = ""
    transformations: list[str] = field(default_factory=list)


@dataclass
class GroupingRules:
    account_key: str = "Account number*"
    holder_key: str = ""
    organisation_key: str = ""
    controlling_person_key: str = ""
    substantial_owner_key: str = ""
    payment_key: str = ""
    reporting_group_key: str = ""
    reporting_fi_key: str = ""


@dataclass
class IdentifierConfig:
    prefix: str = "KY2025BRFI107442"
    country: str = "BR"
    use_uuid: bool = False


@dataclass
class OutputConfig:
    crs_path: str = ""
    fatca_path: str = ""
    pretty_print: bool = True
    append_timestamp_to_name: bool = False
    crs_size_limit_mb: int = 0
    fatca_size_limit_mb: int = 0
    fatca_nil_report: bool = False
    crs_closed_account_zero_balance: bool = True
    crs_closed_account_zero_payment: bool = True


@dataclass
class MappingProfile:
    profile_format_version: str = "1.0"
    app_version: str = "0.1.0"
    name: str = "Perfil padrao"
    declaration: str = "both"
    xsd_hashes: dict[str, str] = field(default_factory=dict)
    sheet_name: str = ""
    header_row: int = 1
    field_mappings: dict[str, MappingRule] = field(default_factory=dict)
    grouping: GroupingRules = field(default_factory=GroupingRules)
    identifier_config: IdentifierConfig = field(default_factory=IdentifierConfig)
    output: OutputConfig = field(default_factory=OutputConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MappingProfile":
        mappings = {
            key: MappingRule(**value)
            for key, value in data.get("field_mappings", {}).items()
        }
        grouping = GroupingRules(**data.get("grouping", {}))
        identifier_config = IdentifierConfig(**data.get("identifier_config", {}))
        output = OutputConfig(**data.get("output", {}))
        clean = dict(data)
        clean["field_mappings"] = mappings
        clean["grouping"] = grouping
        clean["identifier_config"] = identifier_config
        clean["output"] = output
        return cls(**clean)
