# NIVON — Auditoria Transversal de Cobertura do Ledger de Fontes

Data: 20/10/2026. Escopo: `nivon_snapshots` e `nivon_coletas`,
do arquivo SQLite local já existente. **Sem coleta, sem rede, sem deploy.**

## Problema resolvido

O catálogo possui fontes, datasets e rotas, mas *registro no catálogo não
equivale a arquivo efetivamente coletado*. A auditoria estática
`auditoria_coletores.py` mapeia prontidão declarada;
`auditoria_ledger_fontes.py` inventaria unicamente as capturas gravadas
no ledger local fornecido, sem afirmar que o banco representa todos os
ambientes ou que o conteúdo possui homologação externa.

- **Sem banco informado:** counts e timestamps de capturas são `null`,
  estado `BANCO_NAO_FORNECIDO_SEM_EVIDENCIA_DE_COLETA`, **nunca zero**.
- **Banco válido, mas vazio:** zero snapshots **nesse ledger**, sem
  alegar que nunca houve aquisição em outras bases.
- **Snapshot SINTETICO:** separado de snapshot marcado REAL_AUTORIZADO.
  O segundo não prova automaticamente origem, licenciamento, bytes
  preservados, validação ou publicação.
- **Fontes e datasets:** agrupados pelo catálogo canônico atual, sem inventar
  tabelas por fornecedor ou mesclar as saídas de outros storages.
- **Datas:** último timestamp de coleta, frequência de competência,
  referência e publicação nulas por snapshot, anomalias de coleta futura,
  snapshots sem coleta e divergência de identidade fonte/dataset.
- **O que permanece nulo:** volume de observações efetivamente verificadas,
  RAW, direitos de redistribuição e prontidão de publicação.

## Como executar

Sem banco, apenas para demonstrar que a cobertura ainda é desconhecida:

```sh
PYTHONPATH=src python -m nivon.auditoria_ledger_fontes --resumo --prioridade P0
```

Com banco SQLite PRIVADO existente, aberto explicitamente em read-only:

```sh
PYTHONPATH=src python -m nivon.auditoria_ledger_fontes \
  --db /caminho/privado/snapshots.sqlite \
  --gerado-em "2026-10-20T20:00:00Z" --prioridade P0
```

Nenhum banco é criado, mesmo quando o argumento apontar para caminho
inexistente (falha). Arquivos symlink e schemas inesperados falham
fechado. O relatório não lista conteúdo, SHA individual ou dados pessoais.

## Limite da prova

Não consultar tabelas `progresso_edicoes`/`progresso_coletas` do
armazenamento alternativo `progresso_store.py`: são contratos diferentes,
não homologados para soma ou migração. Não interpretar `capturas` como
número de observações, transações, hectares, navios ou toneladas.

Este incremento não modifica `auditoria_coletores.py` nem ativa um
scheduler. Para operação é necessário reconciliar todos os bancos e
fontes, registrar trilhas E2E RAW -> SHA -> parser -> normalização ->
versão -> qualidade -> publicação, testar backups/restores e homologar
licenças e direitos por operação.

## Critérios de aceitação e próximos itens

1. CI executa testes sintéticos de ledger vazio, múltiplas capturas de
   uma mesma edição, banco ausente, datas futuras, registro órfão,
   origem divergente e acesso read-only.
2. Testar contra ledger **real autorizado** em ambiente privado para
   confrontar contagens com o RAW armazenado. Não há esse ensaio neste PR.
3. Planejar estado técnico por dataset em relatório operacional sem
   publicar automaticamente nenhum indicador.
4. Auditar mecanismo alternativo CONAB semanal e eventuais ledgers ANP,
   MDIC e portuários antes de consolidar a cobertura total do NIVON.

**Sem merge/deploy e com controle de custo incremental zero.**
