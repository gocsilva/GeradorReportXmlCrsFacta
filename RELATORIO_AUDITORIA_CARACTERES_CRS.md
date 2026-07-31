# Auditoria de caracteres CRS

Data: 2026-07-31

## Objetivo

Remover definitivamente caracteres especiais dos valores textuais gerados no XML CRS, evitando rejeicoes do portal por conteudo proibido.

## Regra final implementada

Para campos textuais livres do CRS, o app permite somente:

```text
A-Z
a-z
0-9
espaco
```

Qualquer outro caractere e removido ou substituido por espaco antes da gravacao do XML.

Exemplos de caracteres removidos dos textos:

```text
& < > ' " / \ | @ # $ % [ ] { } -- /* &# &amp; &lt; &gt; &apos; &quot;
```

Tambem sao removidos:

- caracteres de controle e invisiveis;
- caracteres XML 1.0 invalidos ou desencorajados;
- acentos e mojibake, convertendo para ASCII seguro.

## Excecoes tecnicas preservadas

Alguns campos nao sao texto livre e precisam manter simbolos para o XSD continuar valido:

| Campo | Motivo | Exemplo |
| --- | --- | --- |
| `ReportingPeriod` | tipo `date` do XSD | `2025-12-31` |
| `BirthDate` | tipo `date` do XSD | `1975-01-15` |
| `Timestamp` | tipo `datetime` do XSD | `2026-07-31T17:10:10` |
| `AccountBalance` | tipo `decimal` do XSD | `155.73` |
| `PaymentAmnt` | tipo `decimal` do XSD | `10.00` |
| `schemaLocation` e `version` | atributos tecnicos do XML/XSD | `CrsXML_v3.0.xsd`, `3.0` |

Essas excecoes sao tecnicas, nao dados textuais livres.

## Pontos corrigidos

- `xml_helpers.add()` agora sanitiza texto com contexto do elemento XML.
- `xml_helpers.atomic_write()` sanitiza novamente a arvore completa antes de salvar, evitando que qualquer valor alterado depois da montagem fique sujo.
- A sanitizacao de atributos remove caracteres especiais de atributos de dados, preservando apenas atributos tecnicos do XML/XSD.
- A aba de limpeza de XML ja gerado passa pela mesma regra central.

## Validacao executada

Foi criado teste de integracao que gera um CRS real com sujeira em:

- `Warning`;
- `Contact`;
- `AccountNumber`;
- `Name`;
- `AddressFree`;
- `City`;
- saldo com virgula.

Depois o teste abre o XML final gravado e valida:

- nenhum texto livre contem caracteres fora de `[A-Za-z0-9 ]`;
- nenhum texto contem `&`, `<`, `>`, aspas, apostrofo, barra, barra invertida, pipe, simbolos ou padroes `--`, `/*`, `&#`;
- nenhuma entidade XML textual como `&amp;`, `&lt;`, `&gt;`, `&apos;`, `&quot;` fica no arquivo;
- saldos continuam validos com ponto decimal.

Status: aprovado para release.
