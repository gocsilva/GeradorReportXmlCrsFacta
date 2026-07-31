# Relatorio de comparacao CRS DITC

Data da analise: 2026-07-31

## Arquivos comparados

- Referencia gerada pelo workbook oficial: `C:\Guilherme\CIIntegracao\docs\ExemploCrs\CRSReport.xml`
- XML gerado pelo nosso app: `C:\Guilherme\GeradorReportXmlCrsFacta_upload\output\crs_compare_reference_release\CRS_nosso_app.xml`
- Workbook usado como base dos dados: `C:\Guilherme\CIIntegracao\docs\ExemploCrs\CRS_XML_Generator_Tool_v2.0 4 (1).xlsm`

## Resultado da validacao

O XML gerado pelo nosso app foi validado contra o XSD CRS embarcado e ficou valido, sem erros.

Resumo estrutural comparado:

| Item | Referencia | Nosso app | Status |
| --- | ---: | ---: | --- |
| `ReportingFI` | 1 | 1 | OK |
| `AccountReport` | 7 | 7 | OK |
| Titulares PF | 3 | 3 | OK |
| Titulares PJ | 4 | 4 | OK |
| `ControllingPerson` | 1 | 1 | OK |
| `AcctHolderType` PJ | `CRS102`, `CRS102`, `CRS102`, `CRS101` | `CRS102`, `CRS102`, `CRS102`, `CRS101` | OK |
| `DocRefId` duplicado | 0 | 0 | OK |

## Diferencas intencionais aplicadas no nosso XML

### 1. `Unique identifier` CRS curto e sequencial

O financeiro confirmou que o `Unique identifier` e o identificador curto, com limite de 10 caracteres, usado para formar o `Document reference`.

O app passou a gerar automaticamente:

```text
KY25000001
KY25000002
KY25000003
...
KY25145000
```

No XML final, esse identificador curto e usado dentro do `MessageRefId` e dos `DocRefId` completos.

Exemplo real gerado pelo nosso app:

```text
MessageRefId: KY2025BRFI107442FIKY25000001
ReportingFI DocRefId: KY2025BRFI107442FIKY25000002
Account DocRefId: KY2025BRFI107442KY25000003
Account DocRefId: KY2025BRFI107442KY25000004
```

Isso preserva a regra informada pelo financeiro:

- `MessageRefId` com pais remetente, ano, pais recebedor e identificador unico.
- `DocRefId` iniciado pela jurisdicao remetente e unico no arquivo.
- `Unique identifier` com no maximo 10 caracteres.

### 2. Conversao de identificadores antigos longos

Se o Excel vier com identificador antigo/comprido, por exemplo:

```text
KY2025BRFI107442001
```

o app converte automaticamente para o identificador curto:

```text
KY25000001
```

Assim evitamos repetir o problema do workbook oficial, onde o campo `Unique identifier` estava preenchido com valor maior do que o limite indicado pela propria planilha.

### 3. `AccountBalance` com ponto decimal

O arquivo de referencia contem saldos com virgula:

```text
155,73
54,18
```

Esse formato falha no XSD CRS porque `decimal` exige ponto como separador decimal.

O app agora garante a saida correta:

```text
155.73
54.18
```

A validacao real confirmou que o nosso XML nao possui saldo com virgula.

### 4. Estrutura de PJ e controlling person

A estrutura CRS de PJ foi mantida conforme esperado:

- PJ sem controlling person: `AcctHolderType=CRS102`
- PJ com controlling person: `AcctHolderType=CRS101`
- CNPJ em `Organisation/TIN issuedBy="BR"`
- `ReportingFI` continua com `IN issuedBy="KY"` e valor `FI107442`

## Conclusao

O XML gerado pelo nosso app esta estruturalmente alinhado ao exemplo oficial e corrige os pontos que causavam rejeicao ou risco de rejeicao:

- `Unique identifier` curto, sequencial e com ate 10 caracteres.
- `MessageRefId` e `DocRefId` completos, unicos e no formato aceito pelo CRS.
- Saldos em formato decimal XML valido, com ponto.
- Tipos CRS de PJ e controlling person preservados.

Status final: apto para release.
