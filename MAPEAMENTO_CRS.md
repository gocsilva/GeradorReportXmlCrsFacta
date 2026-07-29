# Mapeamento CRS

Schema principal: `schemas/crs/v3_0/CrsXML_v3.0.xsd`.

Namespace: `urn:oecd:ties:crs:v3`.

Raiz: `CRS_OECD`.

Campos principais suportados:

- `CRS_OECD/MessageSpec/*`
- `CRS_OECD/CrsBody/ReportingFI`
- `CRS_OECD/CrsBody/ReportingGroup/AccountReport/DocSpec`
- `AccountNumber`, `AccountHolder`, `AccountBalance`, `Payment`
- CRS v3.0: `SelfCert`, `DDProcedure`, `AccountType`, `JointAccount`

Enums são extraídos dos XSDs, não mantidos como fonte duplicada.
