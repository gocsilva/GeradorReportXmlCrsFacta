# Mapeamento FATCA

Schema principal: `schemas/fatca/v2_0_1/FatcaXML_v2.0.1.xsd`.

Namespace: `urn:oecd:ties:fatca:v2`.

Raiz: `FATCA_OECD`.

Campos principais suportados:

- `FATCA_OECD/MessageSpec/*`
- `FATCA_OECD/FATCA/ReportingFI`
- `FATCA_OECD/FATCA/ReportingGroup/NilReport`
- `AccountReport`, `SubstantialOwner`, `PoolReport` estruturalmente previsto no schema
- `FilerCategory`, `DocSpec`, `Payment`

NilReport é mutuamente exclusivo com AccountReport na validação de negócio.
