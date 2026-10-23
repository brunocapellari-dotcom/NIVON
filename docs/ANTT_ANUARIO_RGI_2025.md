# ANTT — fluxo RGI anual a partir de fonte real

## Fonte oficial comprovada
- [Anuário TRC 2025, Tabela 12, página impressa 56](https://www.gov.br/antt/pt-br/assuntos/cargas/dadostrc/anuario_trc_2025_antt.pdf).
- Unidade: toneladas, RGI de origem e destino, competência anual 2025.
- Cobertura: **somente 16 maiores fluxos** listados no relatório, todas as cargas misturadas.
- Não confundir com exportação integral do painel interativo MDF-e/RNTRC, NCM, volumes de grãos ou fluxos mensais.
- Fonte vinculada ao Painel de Movimentação de Cargas. Emissor é a ANTT.
- Data de publicação exata no nível de PDF não foi autenticada pelo extrator e fica NULL. Referência = 2025-12-31; competência=2025; coleta=instante da aquisição.
- A mesma edição contém diferentes denominadores (toneladas totais da movimentação vs recorte mostrado na Tabela 12). Não usar as porcentagens como peso em um total nacional reconstruído, nem somar top-16 como total nacional.

## Código e execução
```bash
PYTHONPATH=src python scripts/ingest_antt_anuario_rgi.py --db /dados/restritos/nivon_antt.sqlite
```
Baixa **um** PDF público de URL fixa e valida HTTPS, assinatura de PDF, tipo MIME, tamanho e ausência de redirecionamento. Usa `pdftotext -layout` para ler a página física 64 (tabela impressa na página 56) e só persiste se obtiver precisamente 16 linhas válidas mais 3 âncoras oficiais verificáveis. Nada é interpolado.

O banco separado mantém `antt_anuario_rgi_lotes` e `antt_anuario_rgi_fluxos`, histórico por SHA-256, observações com ano/UF/RGI/toneladas/percentual e origem. Arquivos idênticos são idempotentes. O dataset **não** mistura granularidades anuais e mensais.

## GitHub Actions
O workflow `antt-anuario-rgi.yml` faz testes sintéticos e, em evento permitido fora de PR, prova de extração de PDF **real** em SQLite efêmero do runner. A limpeza final exclui o SQLite. Logs mostram apenas estado, hash e quantidade de linhas; não publica tabelas ou séries da ANTT em repositório aberto. Há agendamento de verificação mensal no dia 2. A rotina de verificação **não** constitui persistência operacional no Google Cloud.

## Pendente para operação em produção
1. Confirmar resultados e estabilidade do coletor em HTTP/PDF real pelo runner do GitHub.
2. Integrar a persistência ao banco canônico **privado** do NIVON e monitorar revisões de arquivo e qualidade, com credenciais e custos previamente configurados.
3. Obter arquivo/API oficial de matriz MDF-e OD **mensal completa** por competência e NCM para séries temporais e motor de fretes.
4. Armazenar snapshots imutáveis, separar dados observados, inferidos e estimados. Não inferir frete contratado, viagem física nem produto de tabela geral.

Issue de fonte aberta: https://github.com/brunocapellari-dotcom/NIVON/issues/142

## Preparação de saída para BigQuery

O módulo `nivon.antt_anuario_bigquery_export.exportar(banco, saida)` produz JSON Lines a partir do snapshot anual mais recente armazenado em SQLite, com esquema de origem, destino, toneladas e versões de procedência. A saída inclui obrigatoriamente `data_referencia`, `competencia`, `data_publicacao` (nulo enquanto a data exata não for homologada) e `data_coleta`. A tabela proposta fica em `sql/antt_anuario_rgi_bigquery.sql`, particionada por data de referência e clusterizada por UF e RGI.

**A exportação é offline, não envia nada ao BigQuery, não cria serviços, não usa credenciais e não implica go-live.** Não salvar JSONL com toneladas reais em GitHub público. Uma futura etapa autorizada deverá usar carga transacional/idempotente e armazenar histórico privado no projeto Cloud validado.
