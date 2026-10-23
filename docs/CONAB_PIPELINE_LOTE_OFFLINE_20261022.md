# NIVON — Pipeline CONAB em lote (22/10/2026)

## Prioridades de execução e testes

| Prioridade | Implementação | Aceitação | Estado |
|---|---|---|---|
| P0 | HTML do levantamento + anexo + XLSX com hashes independentes | Integridade e vínculo no mesmo lote | Feito offline |
| P0 | Leitura de células por OOXML | String, número Decimal, booleano, sharedStrings, rejeição de fórmula | Feito com workbook sintético |
| P0 | Processar até 30 documentos com rejeição individual | Dossiê JSON por edição, SHA e gate de publicação OFF | Feito |
| P1 | CLI de um comando | Executar pipeline inteiro em subprocesso | Feito |
| P1 | Staging SQLite | Idempotência e preservação de SHAs distintos para a mesma edição | Feito |
| P1 | Teste E2E | Workbook + HTML em disco → CLI → dossiê → SQLite | Feito |
| P2 | RAW oficial com registro de aquisição | Conferir XLSX, SHA, layout e direitos reais | Pendente |
| P2 | Dados agrícolas e backtesting as-of | Validar UF/produto/unidades, edições e disponibilidade | Bloqueado |

## Componentes

- conab_anexo_xlsx_levantamento.py — verifica captura, URLs e ZIP.
- conab_ooxml_metadados.py — mapeia workbook, worksheets e relacionamentos internos.
- conab_celulas_xlsx.py — lê amostras limitadas de células de workbook OOXML; não define indicadores agrícolas.
- conab_lote_offline.py — lote JSON versionado, arquivos relativos dentro de diretório autorizado, SHA-256 de todos os RAWs, resultado por documento e CLI.
- conab_staging_sqlite.py — grava hashes e amostras sem substituir capturas, classificado OFFLINE_SEM_VINTAGE.

O manifesto exige schema_version 1.0 e jobs com job_id, safra, numero_levantamento, pagina_levantamento_url, pagina_anexo_url, arquivo_xlsx_url, os caminhos html_levantamento, html_anexo e xlsx; sha256_html_levantamento, sha256_html_anexo e sha256_xlsx_esperado; coletado_levantamento_em, coletado_anexo_em e coletado_xlsx_em (ISO com fuso). Não aceita links simbólicos, traversal nem saída dentro do diretório RAW.

## Execução em um comando

    PYTHONPATH=src python -m nivon.conab_lote_offline --manifest jobs.json --base-dir capturas --out dossie.json --sqlite conab_staging.sqlite

A opção --sqlite é facultativa. Código de saída 0 significa lote inspecionado, 2 significa ao menos um RAW reprovado e 3 significa erro de contrato/arquivo. A saída não sobrescreve dossiês existentes. O staging local não é o banco canônico agrícola e não fica automaticamente sincronizado ao Cloud.

## Testes automatizados

    PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'

As suítes test_conab_lote_e2e e test_conab_staging_sqlite geram arquivos ZIP OOXML sintéticos com células e exercitam o comando completo em subprocesso, além da persistência SQLite, SHA divergente, symlinks, paths, fórmulas, idempotência e versões alternativas. Os checks de dados oficiais continuam pendentes; não há comprovação de desempenho real.

## Gates de publicação e continuidade

O pipeline sempre retorna habilita_backtest=false, habilita_treino=false e habilita_publicacao=false. A inspeção de um XLSX capturado agora não autentica os dados efetivamente disponíveis no passado. Datas de captura e de publicação não são intercambiáveis. O parsing de conteúdo externo deve ocorrer em worker isolado com limites de memória/tempo, pois os validadores não criam sandbox.

Próxima etapa material: Engenharia de Dados fornecer RAW oficial autorizado com URLs, bytes, SHA e metadados HTTP; executar o lote, aprovar mapeamento real de cultura, produto, unidade e UF e obter evidência independente de cada edição antes de alimentar historico_vintages. Não executar automaticamente merge, deploy, cron, serviços pagos ou WhatsApp.
