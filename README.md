# CRS/FATCA XML Generator

Aplicação desktop offline para Windows que lê arquivos Excel (`.xlsx`/`.xlsm`), permite mapear colunas para campos CRS/FATCA e gera XML validado contra os XSDs fornecidos.

## Requisitos

- Python 3.11+ ou executável em `dist/CRS_FATCA_XML_Generator`.
- Bibliotecas: PySide6, lxml, openpyxl, pandas, pydantic.
- Microsoft Excel não é necessário. Macros de XLSM não são executadas.

## Execução pelo código

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH="src"
python -m crs_fatca_generator.app
```

## Execução pelo EXE

No pacote portatil, abra:

```text
Abrir_Gerador_CRS_FATCA.cmd
```

O pacote portatil nao precisa de permissao de administrador. Copie a pasta inteira para o pendrive e, no outro computador, copie a mesma pasta para `Downloads`, `Documentos` ou `Area de Trabalho`. Mantenha o `.cmd`, o `.exe` e a pasta `_internal` juntos.

## Uso

### Modo simples

1. Clique em **Selecionar Excel**.
2. Escolha a planilha com os dados.
3. Clique em **Executar agora**.

O aplicativo valida se as colunas obrigatórias estão presentes e salva automaticamente os XMLs em uma pasta `XML_Gerados` ao lado do Excel selecionado. Se a pasta do Excel estiver bloqueada, o programa usa automaticamente `Documentos\CRS_FATCA_XML_Gerados\<nome_do_excel>`. Na mesma pasta também são criados `*_relatorio_auditoria.csv`, `*_relatorio_auditoria.xlsx` e `*_manifesto_auditoria.json`, com documentos e contas mascarados.

Nenhuma configuracao manual e necessaria para o fluxo principal. Dados internos do sistema, como logs e historico de identificadores, ficam automaticamente no perfil local do usuario do Windows.

Configuração padrão deste projeto:

- CRS: `TransmittingCountry = KY`, `ReceivingCountry = BR`, `MessageType = CRS`, moeda `USD`.
- FATCA: `TransmittingCountry = KY`, `ReceivingCountry = US`, `MessageType = FATCA`, moeda `USD`.

Moeda e país são informações independentes: `currCode="USD"` não altera país transmissor, país receptor, residência fiscal, endereço ou país emissor do TIN.

Antes de gerar o XML, o modo simples aplica as regras oficiais configuradas para este projeto:

- remove contas com encerramento efetivo no CI antes de `2025-01-01`;
- remove contas sem encerramento efetivo no CI quando o status CC for `Encerrada` ou `Encerrada Bacen` durante 2025;
- para o mesmo documento com mais de uma conta CI remanescente, remove a conta de menor número;
- normaliza e valida CPF/CNPJ brasileiros, incluindo zeros à esquerda;
- converte saldo negativo para `0.00` e mantém a conta no XML;
- bloqueia a geração quando CPF/CNPJ inválido ou documento em notação científica não recuperável for encontrado.

### FATCA e US Tax ID

No FATCA, CPF/CNPJ brasileiro nao e usado automaticamente como US Tax ID. O gerador so emite `sfa:TIN issuedBy="US"` quando houver campo especifico `US_TAX_ID` valido. Planilhas antigas sem `US_TAX_ID` continuam gerando XML tecnico de teste com o `TIN` do titular omitido, pois o XSD FATCA v2.0.1 permite `TIN minOccurs=0`. A politica central segura e `BLOCK_PRODUCTION`; o modo simples usa `TECHNICAL_TEST_ONLY` para homologacao e marca o relatorio como pendente de decisao fiscal.

Campos suportados para planilhas novas:

- `US_TAX_ID`
- `US_TAX_ID_ISSUED_BY`
- `US_TAX_ID_STATUS`
- `US_TAX_ID_REASON`

Valores ficticios como `NULL`, `N/A`, `SEM TIN`, `000000000`, numero da conta, FI Number, CPF ou CNPJ sao bloqueados como US Tax ID.

Colunas obrigatórias para o layout simples:

- `DocumentoCliente`
- `Tipo de documento`
- `NumConta`
- `NomeCliente`
- `SaldoTotal`
- `Endereco`
- `Cidade`
- `Estado`
- `Pais`

### Modo avançado

1. Em **Excel**, selecione o arquivo, a aba e a linha de cabeçalho.
2. Em **Declaração**, marque CRS, FATCA ou ambos e confirme os schemas.
3. Em **Informações**, preencha dados gerais da mensagem e ReportingFI.
4. Em **Mapeamento**, associe campos a colunas, valores fixos, automáticos ou vazios.
5. Em **Agrupamentos**, defina a chave de conta e demais chaves quando necessário.
6. Em **Validação e geração**, escolha destinos separados para CRS e FATCA, visualize e gere.

Para o layout de `ExemplosDados/schema_mock.xlsx`, o aplicativo reconhece automaticamente colunas como `DocumentoCliente`, `Tipo de documento`, `NumConta`, `NomeCliente`, `SaldoTotal`, `Endereco`, `Cidade`, `Estado` e `Pais`. Também preenche os padrões do Reporting FI descritos em `ExemplosDados/dados.md`.

Campos opcionais vazios não são emitidos. Campos fiscais sensíveis são mascarados na pré-visualização e logs técnicos ficam no perfil local do Windows.

## XML internacional CRS/FATCA versus leiaute brasileiro da e-Financeira

Este software gera XML conforme os XSDs internacionais fornecidos: `CrsXML_v3.0.xsd` e `FatcaXML_v2.0.1.xsd`. A aceitação por um órgão receptor depende da jurisdição. O Brasil pode exigir eventos, envelopes, certificados, assinaturas digitais e leiautes próprios da e-Financeira. Um módulo brasileiro deve ser implementado separadamente com base nos XSDs e manuais oficiais vigentes.

## Build do executável

```powershell
.\build_exe.ps1
```

ou:

```bat
build_exe.bat
```

O build usa PyInstaller em modo one-folder e inclui `schemas/` e `assets/`.

## Troubleshooting

- Se o XML for inválido, abra a tabela de erros e revise elemento, mensagem e sugestão.
- Se um XSD importado estiver ausente, confira a pasta `schemas`.
- Se o EXE não abrir, execute `python -m crs_fatca_generator.app --self-test` pelo código para isolar dependências.
