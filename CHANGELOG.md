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
- Corrige travamento aparente ao selecionar Excel grande: a interface carrega somente a previa e a leitura completa ocorre em segundo plano ao executar.
- Adiciona progresso de leitura com registros processados, faltantes, registro/linha atual e previsao de finalizacao.
- Adiciona progresso detalhado na geracao do XML: etapa atual, XML CRS/FATCA, conta atual, progresso por conta, tempo decorrido e ultima atualizacao.
- Adiciona progresso interno na preparacao/auditoria e reduz eventos repetidos em arquivos grandes, evitando tela parada em "Preparando dados".
- Otimiza geracao sequencial de MessageRefId/DocRefId para nao reiniciar a busca de IDs a cada conta.
- Adiciona log em tempo real na tela de validacao/geracao, com etapas, contadores, registro atual e ETA.
- Otimiza auditoria para arquivos grandes: CSV completo, XLSX resumido/amostral e manifesto amostral para evitar travamento visual em "Gerando auditoria".
- Remove buscas quadraticas na auditoria usando indices por linha e por conta.
- Permite uma segunda geracao ignorando registros com erro de linha, registrando as remocoes na auditoria como `ERRO_IGNORADO`.
- Adiciona limite opcional de tamanho por XML CRS/FATCA; `0 MB` significa sem limite e partes respeitam `AccountReport` inteiro.
- Adiciona aba para dividir XML CRS/FATCA existente em partes por tamanho sem quebrar registros.
- Adiciona checkboxes de geracao CRS/FATCA marcados por padrao e respeitados pelo botao simples.
- Aplica filtro CRS por `USPerson = true` quando a coluna existe no Excel.
