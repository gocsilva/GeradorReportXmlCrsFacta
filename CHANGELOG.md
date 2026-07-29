# Changelog

## 0.1.0

- Implementa aplicação PySide6 offline para geração CRS/FATCA.
- Inclui schemas reais extraídos, validação XSD, perfis JSON, SQLite de identificadores e build PyInstaller.
- Simplifica o fluxo para selecionar Excel e clicar em Executar.
- Define moeda padrão USD e separa ReceivingCountry CRS/FATCA no gerador.
- Inclui preparacao oficial dos dados antes do XML: regras 01/02/03, CPF/CNPJ validado, saldo negativo zerado e auditoria CSV/XLSX.
- Separa US Tax ID do documento brasileiro no FATCA, omite TIN ausente conforme XSD em modo teste e adiciona relatorio de pendencias.
- Amplia auditoria para XLSX multiabas, CSV registro a registro, manifesto JSON, validacao XSD, conciliacao e identificadores DITC sequenciais sem UUID.
- Reforca pacote portatil sem administrador: abrir pelo `.cmd`, dados internos no perfil do usuario e saida automatica sem configuracao manual.
