# NIVON — operação P0 de CEPEA, IMEA e CONAB

**Estado verificado em 23/10/2026, horário de Mato Grosso.** Os dados do Google Drive não são tratados como atualização oficial. Um arquivo modificado não altera datas de referência ou publicação. Estado descrito conforme PostgreSQL Neon e execuções GitHub Actions.

## Estado operacional auditado

| Fonte | Leitura e banco | Automação | Estado atual |
|---|---|---|---|
| CEPEA | 30 preços de soja, duas séries (Paranaguá, Paraná), com referência em 21/10/2026 | GitHub Actions na main, soja 23h UTC e milho 23h45 UTC em dias úteis | **COLLECTOR_ERROR** para soja: última tentativa HTTP 522. Milho ainda sem registros persistidos. |
| IMEA | **1.012 registros em staging**, soja 107, milho 110, algodão 111, bovinocultura 684. Fonte oficial verificada. | Workflow na main; inicialmente comprovado 10h/19h MT para soja/milho. Verificar inclusão e agenda efetiva das demais cadeias antes de declará-las recorrentes. | **STAGING_PUBLICATION_ONLY**: todas as linhas têm `reference_date=NULL`. Nenhuma deve entrar como cotação diária de fechamento. |
| CONAB | 4 registros de levantamentos MT, 14 de balanços soja/milho, 32 safras históricas 2010/11–2025/26 | Main: dias úteis 17h UTC (13h MT), histórico integral às quartas | **ACTIVE**. Primeiro teste E2E na main aprovado e idempotente; próximas agendas precisam comprovar continuidade. |

### Evidências reais
- CEPEA [30 preços no Neon](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39856137721), [erro de origem HTTP 522 e gravação de alerta OIDC](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39943843277). A falha foi inserida em `nivon_p0_source_checks` como `PRIMARY_SOURCE_FAILURE`, sem alterar as cotações.
- IMEA [primeira ingestão soja/milho](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894377921), [deduplicação](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894495044), [sucesso na main](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894592868). Total com algodão e bovinos conferido diretamente na tabela `nivon_imea_prices_staging`.
- CONAB [carga e idempotência na main](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39895201422); [histórico](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39702302650).

### Separação obrigatória de dados e licenças
- `public.nivon_p0_drive_inventory`: **21 arquivos históricos** do Drive: CEPEA 1, IMEA 4, CONAB 16; `promoted_to_current=FALSE`.
- `reference_date`, `published_at`, `collected_at`, `crop_year` e `competencia` representam conceitos distintos. Campo ausente não pode ser preenchido artificialmente.
- O IMEA foi autorizado pelo responsável pelo NIVON na conversa; `provider_document_verified=FALSE` e `auth_state=PENDING_WRITTEN_PERMISSION` permanecem, pois não foi apresentado documento do provedor. Não tornar dados do IMEA públicos nem distribuir base bruta de terceiros por essa declaração.
- CEPEA: preços de páginas públicas são CC BY-NC 4.0 com atribuição; API contratada oficial possui termos específicos. Ela **não foi habilitada** no NIVON e não se deve pressupor gratuidade ou endpoint sem credenciais.
- CONAB: publicações oficiais e edições de safra são separadas de séries históricas, com versões e hashes; projeções não são produção realizada.

### Banco e motores
- `nivon_p0_sources`, `nivon_p0_source_checks`: permissões, estado e execução observada.
- `nivon_p0_frescor`, `nivon_p0_series_status_v`: status por fonte e por série; erros CEPEA isolados por URL soja/milho. `COLLECTOR_ERROR` nunca equivale a preço novo.
- `nivon_cepea_variacao_diaria_v`: variação descritiva diária apenas com preço CEPEA observado e referência explícita.
- `nivon_conab_producao_anual_v`: comparação anual das safras históricas da CONAB.
- `nivon_imea_indicadores_verificados_v`: IMEA com `PUBLICACAO_SEM_REFERENCIA` não é elegível para tendência diária.
- `nivon_imea_staging_saude_v`: estado do coletor, mesmo em dias sem novas publicações.
- `nivon_imea_comparativo_publicacoes_v`: compara versões por publicação sem fingir data de cotação; o resultado pode não ter observações anteriores comparáveis por indicador.

## Próximas ações por impacto
1. CEPEA: manter tentativas limitadas e registro automático de incidentes. Diagnosticar HTTP 522 junto ao provedor, ou integrar **API oficial autorizada** caso acesso/termos/credenciais sejam obtidos. Não usar Notícias Agrícolas como se fosse CEPEA.
2. CEPEA: coletar milho somente após restabelecer acesso e confirmar referência, unidade e praça.
3. IMEA: confirmar próxima rodada de cron efetivamente disparada, anomalias e revisões; expandir cobertura sem misturar datas de publicação com cotação.
4. CONAB: acompanhar novos levantamentos e auditar cron em dias diferentes; expandir produtos/UFs após sucesso continuado.
5. Todas: monitoramento de falhas persistentes, backup e integração controlada aos motores por estado de qualidade.

Links: [Termos de API do CEPEA](https://onetoone.cepea.org.br/termocontratacao-regulamentoapi/) · [Termo do IMEA](https://imea.com.br/imea-site/termo-de-uso.html) · [CONAB](https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras).

## Monitor de integridade operacional — 23/10/2026
- Arquivos: `nivon/monitor_p0_workflows.py` e `tests/test_monitor_p0_workflows.py` (10 testes de regressão aprovados).
- GitHub Actions em **main**: `.github/workflows/monitor-p0-operacao.yml`, agenda em dias úteis 12h15 UTC (08h15 MT), leitura de histórico de execução no GitHub API e artefato `status_p0.json` com retenção de 14 dias.
- Execução inicial https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39947411726 : **CEPEA=EXECUTION_FAILURE**, **IMEA=SCHEDULE_NOT_OBSERVED**, **CONAB=SCHEDULE_NOT_OBSERVED**. A falha do job é proposital quando existe problema operacional real e permanece visível no GitHub.
- `SCHEDULE_NOT_OBSERVED` significa que ainda não foi verificado disparo do evento `schedule`; `push` e `workflow_dispatch` não são contados como comprovação de recorrência.
- **Visão operacional em Neon:** `nivon_p0_precos_operacionais_v` só mostra CEPEA com `reference_date` recente, `operational_status=CURRENT_AND_ACTIVE` e fonte original comprovada. Com CEPEA HTTP 522, retorna corretamente **0 preços elegíveis**, preservando os 30 históricos. IMEA permanece sem `reference_date`, e CONAB usa sua visão separada de safras.
- **Bloqueio CEPEA:** repetidas falhas HTTP 522 e timeouts de origem em 23/10. Não alterar preciosidade nem tratar dados do Drive como novos. API CEPEA oficial tem autorização e condições específicas, ainda sem credencial/NIVON confirmada.

### Política de alertas de cron
- O watchdog está fixado no commit testado `12c47099651ccb2cb9479c87f13019535877045a` na `main`, com [10 testes aprovados](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39947347736).
- Diferencia `SCHEDULE_NOT_OBSERVED` (ativação recente) de `SCHEDULE_MISSING` após **dois horários agendados vencidos** sem confirmação. Evita confundir uma execução manual de sucesso com agendamento funcional.
- Verificação final no [GitHub](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39947411726): CEPEA `EXECUTION_FAILURE`, IMEA e CONAB `SCHEDULE_NOT_OBSERVED`; o job sinaliza intencionalmente erro enquanto o CEPEA permanecer indisponível.
- Consulta no Neon após criar `nivon_p0_precos_operacionais_v`: **0 preços operacionais**, **30 preços CEPEA históricos preservados**, IMEA **1.012 registros de publicação sem data de referência**, CONAB **32 séries históricas**. Nenhuma observação antiga foi promovida como atual.
