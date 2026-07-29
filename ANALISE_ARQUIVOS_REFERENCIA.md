# Análise dos Arquivos de Referência

Arquivos encontrados inicialmente:

- `CRS_XML_Generator_Tool_v2.0.xlsm`: planilha CRS v2.0 com abas `Instructions`, `Report information`, `Individual accounts`, `Organisation accounts`, `Generate return`, `Lookups`; contém VBA e controles, mas a aplicação não executa macros.
- `FATCA_XML_Generator_Tool_v2.0.xlsm`: planilha FATCA v2.0 com as mesmas abas principais; contém NilReport e listas FATCA.
- `xml-schema-crs.zip`: extraído para `reference_extracted/crs` e copiado para `schemas/crs/v3_0`.
- `fatcaxml-v2-0-1.zip`: extraído para `reference_extracted/fatca` e copiado para `schemas/fatca/v2_0_1`.

Divergências:

- As planilhas limitam operacionalmente a 50 contas; o software não impõe esse limite.
- CRS v3.0 exige campos ausentes ou incompletos na planilha antiga, como `SelfCert`, `DDProcedure`, `AccountType` e novos enums.
- O XSD foi priorizado na ordem, cardinalidade e validação.
