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


## Segunda trilha entregue: histórico de progresso presente no Drive

Pesquisa real no Google Drive conectado identificou o arquivo
[CONAB_Plantio_Colheita_Historico.xlsx](https://docs.google.com/spreadsheets/d/1CsSAwovXncudDw1S0XDh8z9wNin04Qt4/edit)
com MIME XLSX e tamanho informado pelo Drive de 794.067 bytes, criado em 10/08/2026.
A leitura conectada de texto retornou **17.982 registros**, em **10 colunas**, cobrindo
**08/11/2019 a 31/07/2026**. O perfil do texto confirmou:
- Operações: Semeadura e Colheita.
- Produtos: Soja, Milho 1ª, Milho 2ª e Algodão.
- 12 estados: BA, GO, MA, MT, MS, MG, PR, PI, RS, SC, SP e TO.
- Campo Dado em fração 0..1; campo INFO apenas Brasil ou MT (rótulos da origem, nunca média municipal/nacional).
- Nas 17.982 linhas lidas, não houve divergências encontradas de índice sequencial, semana ISO, ano, relação INFO/MT ou fração fora de 0..1.

**Atenção:** a inspeção ocorreu via conversão textual do conector Drive;
não foi materializado o XLSX binário original nem recalculado seu SHA-256.
As datas Data são referências das observações, não provas de publicação original.
A última referência é julho de 2026; o documento NÃO substitui a coleta atualizada
da CONAB nem permite backtest point-in-time de séries futuras.

Implementado o adaptador independente
src/nivon/conab_progresso_csv_drive.py, que aceita **CSV exportado do XLSX**
com hash de aquisição obrigatório, valida todas as linhas, datas, operações,
estados, produtos e frações, e produz uma série normalizada com
publicado_em=null, disponivel_em=null e todos os gates OFF.
O importador não reutiliza o parser de boletins mensais: progresso de
semeadura/colheita (fração) é dado distinto de produção, produtividade,
área e oferta/demanda, evitando mistura de unidades.

Comando quando o RAW CSV estiver exportado localmente:

    PYTHONPATH=src python -m nivon.conab_progresso_csv_drive --input progresso_conab.csv --sha256 SHA256_DO_CSV_REAL --adquirido-em 2026-10-22T09:00:00-04:00 --out progresso_staging.json

Os horários e hash do comando são placeholders exemplificativos.
tests/test_conab_progresso_csv_drive.py valida três linhas de schema
derivadas da leitura conectada do arquivo do usuário e faz smoke test do CLI;
não utiliza a totalidade de linhas em CI e não declara autenticação do XLSX original.

### Bloqueios remanescentes

1. Para produção histórica mensal: adquirir HTML+XLSX da edição original
   diretamente de fonte autorizada e conferir bytes, hash e layout real.
2. Para progresso semanal: montar coletor oficial CONAB com carimbo de
   publicação e versão por levantamento, sem usar o Drive de agosto como
   substituto de novas publicações.
3. Para operacionalização: integrar staging ao banco de dados autorizado
   com custeio e acesso verificados; não promover automaticamente a
   tabelas de séries canônicas, modelos ou dashboards.
