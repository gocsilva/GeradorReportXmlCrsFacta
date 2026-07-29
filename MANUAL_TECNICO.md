# Manual Técnico

Arquitetura:

- `models`: dataclasses internas para MessageSpec, ReportingFI, Party, AccountReport, Payment e perfis.
- `services`: leitura Excel, inspeção XSD, mapeamento, agrupamento, validação de negócio, geração XML e validação XSD.
- `gui`: interface PySide6.
- `infrastructure`: paths, SQLite local e logging rotativo.
- `security`: parser XML seguro e mascaramento.

Pipeline:

```text
Excel -> linhas normalizadas -> modelos internos -> XML lxml -> validação XSD
```

Os parsers XML usam `resolve_entities=False` e `no_network=True`. Imports/includes são resolvidos por arquivos locais.
