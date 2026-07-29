# Manual do Usuário

O fluxo principal agora e simples: selecione o Excel e clique em **Executar agora**. O sistema detecta o layout dos exemplos, verifica colunas faltantes e salva CRS/FATCA em `XML_Gerados` ao lado do Excel.

## Uso sem permissao de administrador

O pacote portatil nao precisa ser instalado. Copie a pasta inteira para o pendrive e, no outro computador, copie a mesma pasta para `Downloads`, `Documentos` ou `Area de Trabalho`. Abra `Abrir_Gerador_CRS_FATCA.cmd`.

O programa grava logs e historico de identificadores em pasta do proprio usuario. Se nao conseguir salvar `XML_Gerados` ao lado do Excel, ele muda automaticamente para `Documentos\CRS_FATCA_XML_Gerados\<nome_do_excel>`.

Nenhuma configuracao manual e necessaria: abra o `.cmd`, selecione o Excel e clique em **Executar agora**.

Neste projeto, o modo simples usa CRS `KY -> BR` e FATCA `KY -> US`, sempre com saldos em `USD`.

Tambem sao gerados relatorios de auditoria em CSV e XLSX, alem do manifesto JSON, na pasta `XML_Gerados`. Eles mostram remocoes, ajustes, erros, validacao XSD, conciliacao, identificadores e pendencias com documento e conta mascarados.

Antes do XML, o software remove contas fora da regra de encerramento, remove a menor conta quando o mesmo documento aparece em mais de uma conta CI, valida CPF/CNPJ e transforma saldo negativo em `0.00`.

No FATCA, CPF/CNPJ brasileiro nao e usado como US Tax ID. Enquanto a area fiscal nao confirmar o tratamento definitivo, o software omite o `TIN` do titular FATCA quando `US_TAX_ID` estiver ausente em modo `TECHNICAL_TEST_ONLY`, marca o XML como teste e registra tudo na aba `Pendencias US Tax ID` do relatorio. A politica segura para producao e `BLOCK_PRODUCTION`.

O aplicativo tambem mantem telas avancadas em etapas. Nelas voce pode conferir a previa, escolher CRS/FATCA, alterar informacoes gerais, ajustar mapeamentos e gerar os XMLs.

Perfis podem ser salvos e abertos pelo menu **Arquivo**. O perfil armazena mapeamentos, valores fixos, agrupamentos e saída, mas não deve receber dados fiscais reais salvo valores fixos definidos conscientemente.

Para arquivos com várias linhas por conta, informe a coluna da chave da conta em **Agrupamentos**. O sistema agrupa linhas iguais antes de gerar o XML.

Erros são exibidos de forma amigável. Um XML inválido não é tratado como sucesso.
