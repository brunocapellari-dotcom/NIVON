# NIVON — Coleta pontual CONAB e auditoria temporal (23/10/2026)

## Prioridades e execução

| Prioridade | Entrega | Situação |
|---|---|---|
| P0 | Captura pontual: três URLs oficiais por edição, validação de MIME/URL/SHA, metadados HTTP, diretório RAW atômico, contrato jobs.json | IMPLEMENTADO; rede oficial não acessível neste executor |
| P0 | Handoff RAW → worker Linux → dossiê e SQLite staging | IMPLEMENTADO e testado E2E com respostas HTTP sintéticas |
| P0 | Auditoria temporal do histórico real de progresso identificado no Drive | IMPLEMENTADO; perfil de 17.982 linhas lidas via conector |
| P1 | Falha fechada para captura inválida, redirecionamento, SHA, documento incompatível e falsa disponibilidade passada | IMPLEMENTADO |
| P1 | Obter XLSX mensal oficial real e homologar abas/unidades/UF | PENDENTE de conectividade e verificação |
| P2 | Usar os dados em séries históricas, modelos e backtesting as-of | BLOQUEADO até prova independente de edição e disponibilidade |

## Captura oficial de uma edição em um único comando

```bash
PYTHONPATH=src python -m nivon.conab_coleta_pontual \
  --safra 2023/24 --levantamento 3 --destino capturas \
  --dossie dossies/conab_2023_24_l03.json --sqlite conab_staging.sqlite
```

Pré-condições: diretórios capturas/ e dossies/ existentes, saída inédita e máquina Linux com acesso HTTPS www.gov.br. O comando aceita exclusivamente uma edição de config/conab_levantamentos_candidatos.v1.json. Não faz crawling, cron nem coleta em massa. Baixa HTML do levantamento, HTML de visualização do anexo e XLSX binário; confere link entre os arquivos, MIME, limites de 3 MB/3 MB/15 MB, HTTP 200, domínio e redirecionamento CONAB e carimbos de captura. Registra SHA-256 de cada RAW, URL final, ETag e Last-Modified, quando retornados.

Os cinco arquivos preservados em diretório de edição atômico são levantamento.html, anexo.html, tabela.xlsx, jobs.json e captura_http.json. O destino de uma edição existente não é sobrescrito. Com --dossie, é invocado o worker Linux limitado de conab_lote_isolado; --sqlite grava apenas staging OFFLINE_SEM_VINTAGE. A inspeção não impede rede dentro do subprocesso: arquivos não confiáveis exigem contêiner ou VM adicional sem rede, sem credenciais e com filesystem controlado.

Mesmo um download autêntico agora NÃO comprova os mesmos bytes disponíveis na data histórica da publicação. Captura atual, data declarada do portal, ETag e Last-Modified não representam evidência independente de vintage. Toda operação preditiva, backtest e publicação permanece OFF.

## Histórico real de progresso acessível no Google Drive

Arquivo: https://docs.google.com/spreadsheets/d/1CsSAwovXncudDw1S0XDh8z9wNin04Qt4/edit — CONAB_Plantio_Colheita_Historico.xlsx, MIME Excel, 794.067 bytes segundo pesquisa Drive, criado em 10/08/2026. Os números abaixo foram calculados sobre os 17.982 registros de TEXTO retornados pelo conector em 23/10/2026. O XLSX binário original não foi materializado, nem houve conferência do hash desse original.

- Cobertura: 08/11/2019 a 31/07/2026; 432 datas distintas; 74 grupos de estado×produto×operação, 12 estados, MT com 1.369 observações.
- Operações: Semeadura 12.247; Colheita 5.735.
- Produtos: Soja 6.172; Milho 1ª 5.048; Milho 2ª 3.528; Algodão 3.234.
- Validação do texto: 17.982 linhas com 10 colunas, valores no intervalo 0..1, sem chaves semanais duplicadas e sem ano/data incompatíveis detectados na inspeção.
- Sucessivos registros de cada grupo, na ordem fornecida pelo arquivo, apresentam 732 reduções de fração, 546 superiores a 25 pontos percentuais e 406 intervalos maiores que 60 dias. **Isso não prova 732 erros ou tendência de baixa**: inclui reinício de safra, possível correção e lacunas de cobertura.

O novo módulo conab_progresso_auditoria.py calcula cobertura, hiatos, quedas de fração e amostra de eventos sem inferir ano-safra. O importador conab_progresso_csv_drive.py ganhou --auditoria-out para produzir histórico normalizado e relatório de qualidade em uma execução:

```bash
PYTHONPATH=src python -m nivon.conab_progresso_csv_drive \
  --input progresso_conab.csv --sha256 HASH_REAL_DO_CSV \
  --adquirido-em DATA_REAL_COM_FUSO --out progresso_staging.json \
  --auditoria-out progresso_qualidade.json
```

O comando depende da exportação CSV real, do SHA e da hora de aquisição efetiva. Não considera o arquivo de agosto/2026 uma fonte live, nem reconstitui os boletins originais. Todos os campos de disponibilidade histórica e os gates de modelos/publicação permanecem falsos.

## Validação e próxima atividade

Testes E2E cobrem captura HTTP simulada com três RAWs → manifesto → worker Linux real → SQLite, URLs alteradas, duplicata, aquisição parcial e SHA divergente; e CSV sintético → normalização → relatório de qualidade por comando único. Não há teste de rede gov.br real porque o executor não resolve www.gov.br (DNS).

CI da implementação antes desta documentação: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984491806 — 1.333 testes, zero falhas, cinco ignorados. Verificar novamente após commit documental.

Próximo P0: executar o comando pontual em infraestrutura autorizada com conectividade, conferir licenciamento e direitos, preservar bytes e verificar layout/UF/unidades/valores da primeira edição mensal. Não houve deploy, cron, envio de WhatsApp, gasto ou merge em main.
