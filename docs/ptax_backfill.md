# PTAX — backfill reentrante e requisitos para operação durável

Estado em **21/10/2026**: implementação/testes de integração aprovados; **não operacional em produção**. A PR #58 está em revisão, com código executado em runners do GitHub e sem persistência entre execuções.

## Evidências técnicas verificáveis

- Testes offline: 29 passaram. Abrangem dados reais simulados, URLs OData, normalização por moeda, revisões, idempotência, datas, dados ausentes, checkpoints, retomada após falha, saída sem cotações e isolamento do banco.
- Histórico REAL do Banco Central: workflow \`PTAX - backfill real e retomada\`, https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39637991317
- Período 01/01/2026 a 10/02/2026, USD: **2 janelas**, **28 observações**, segunda execução com **0 consultas novas**, sem duplicação. SQLite apenas no diretório efêmero do runner.
- A coleta anterior de 20/09/2026 a 21/10/2026 comprovou **21 USD** e **108 EUR** em endpoints de granularidade diferente: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39629618928
- 42 IDs de widget Notícias Agrícolas são catálogo de exibição, **não API licenciada**.

## Executar somente num host com disco privado persistente

Sem agendamento/deploy presumido, o operador configura diretório **fora do checkout do GitHub**. O código bloqueia caminhos que apontem para dentro do repositório público, inclusive links simbólicos.

\`\`\`bash
install -d -m 700 "$HOME/.local/share/nivon"
export NIVON_PTAX_DB="$HOME/.local/share/nivon/ptax.sqlite3"
python -m nivon.ptax_backfill --moeda USD \
  --inicio 2026-01-01 --fim 2026-12-31 --banco "$NIVON_PTAX_DB" --dry-run
python -m nivon.ptax_backfill --moeda USD \
  --inicio 2026-01-01 --fim 2026-10-21 --banco "$NIVON_PTAX_DB" \
  --max-janelas 8 --intervalo-segundos 0.5
# Repetir o comando anterior até estado COMPLETO, sempre com o mesmo intervalo e dias-janela.
python -m nivon.ptax_bcb --moeda AMBAS --banco "$NIVON_PTAX_DB"
\`\`\`

As datas acima são **exemplos ilustrativos**, não evidência de execução nesse host. Cada rodada de backfill processa no máximo oito janelas de até 31 dias. Registra estado, tentativas, registros e falhas por janela na tabela \`ptax_backfill_janelas\`. Janelas antigas concluídas são puladas; janelas dos últimos 7 dias são reconsultadas. A flag \`--revalidar\` reprocessa tudo no intervalo solicitado, preservando revisões.

**Importante:** \`COMPLETO\` significa que **todas as janelas daquele intervalo e moeda** receberam respostas válidas (inclusive dias sem publicação). Não significa que cada dia tenha cotação, nem que toda a série histórica do BCB esteja disponível no banco. Periodicidade, calendário e histórico total exigem controles adicionais.

## Banco e qualidade

- Duas tabelas existentes: \`ptax_observacoes\` (valores e versões) e \`ptax_execucoes\` (logs de lote). A terceira, \`ptax_backfill_janelas\`, adiciona checkpoints por moeda/início/fim.
- Valor precisa ser Decimal positivo; moeda e data validadas pela resposta OData; \`data_publicacao\` é nula quando a API não a fornece; datas de coleta são UTC real.
- Correções de boletim (compra e/ou venda) não substituem silenciosamente a versão anterior.
- O armazenamento SQLite não mantém criptografia em repouso por padrão; aplicar controles do host (permissões de arquivo, backups privados, disco criptografado quando necessário).
- A licença ODbL do BCB exige observar atribuição e obrigações aplicáveis. Dados e bancos não devem ser adicionados ao repositório público sem verificação das condições.

## Próximas validações essenciais

1. Selecionar e comprovar **armazenamento privado persistente** com backups e execução entre reinícios — **não existe neste projeto ainda**.
2. Backfill retrospectivo progressivo USD/EUR com contagem, logs, custo/taxa e reconciliação das janelas. Não consultar décadas indiscriminadamente sem governança.
3. Implantar serviço agendado no host persistente, com lock de execução, alertas de falha e atraso; confirmar operação real em dias consecutivos.
4. Incluir calendário de feriados e validadores de qualidade antes de publicar freshness como definitivo.
5. Somente depois integrar os indicadores da PTAX ao motor de tendência e abrir IMEA/CEPEA conforme permissões.

Nenhuma infraestrutura externa foi provisionada, nenhum custo foi autorizado e não há rotina de armazenamento definitivo ativa.
