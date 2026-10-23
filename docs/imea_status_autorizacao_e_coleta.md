# IMEA — autorização informada e primeira coleta pública
Atualização: 22/10/2026.

## Autorização
O responsável pelo NIVON declarou em conversa: **“imea autorizado”**. Trata-se de declaração do responsável, **não de uma confirmação independente do IMEA**; o texto da autorização, se concedida pelo IMEA, e seu escopo exato ainda não foram apresentados.

Termo oficial: https://imea.com.br/imea-site/termo-de-uso.html.
As séries públicas da API IMEA são descritas em https://agrobr.dev/docs/sources/imea/ como `zona_cinza`, e o acesso público não implica automaticamente permissão genérica para redistribuição ou uso de arquivos não públicos. Não fazer bypass de controle, não compartilhar credenciais, não disponibilizar base bruta de terceiros publicamente.

## Validação real
Execução https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39891236618 :
- Soja: **4.568 registros de origem**, **107 candidatos a preço/frete**, última data de publicação 2026-10-22;
- Milho: **5.986 registros de origem**, **110 candidatos a preço/frete**, última data de publicação 2026-10-21;
- `meta.source=imea`, URLs oficiais `api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes` e `.../3/cotacoes` comprovadas;
- quatro testes isolados passaram (`tests/test_imea_publico.py`);
- Nesta validação antiga os dados estavam em memória. **A carga real posterior já gravou 217 registros em staging**, como evidenciado abaixo;
- `reference_date` por linha: não fornecida; `published_at` é publicação, não cotação de referência.

## Implementado
- `nivon/imea_publico.py`: normalização por cadeia, ID textual (inclusive 18 dígitos), unidade, localidade, safra, hash para revisões; zero e semente fora dos preços físicos aprovados;
- `.github/workflows/imea-validacao.yml`: consulta pontual real sem persistência;
- `database/neon_imea_prices_staging.sql`: tabela separada no Neon para registros de publicação, com `reference_date` nullable;
- `nivon_imea_access_attestations`: registro da declaração do responsável; `provider_document_verified=FALSE`.
- O registro de fonte era inicialmente bloqueado. **A ingestão em staging está ativa**; a documentação do provedor permanece não verificada e a liberação analítica continua separada.

## Monitoramento recorrente e contratos de integração
- `nivon/imea_lotes.py`: processamento incremental de até 80 observações por lote, deduplicação exata e relatório de rejeições sem divulgar valores no GitHub.
- `tests/test_imea_lotes.py`: seis testes de lotes, origem oficial, troca de cadeia, ausência de data de referência, limites de tamanho e duplicatas. `tests/test_imea_publico.py` ampliado para oito testes. Total **14/14 aprovados**: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39892153962.
- `main/.github/workflows/imea-publicacoes-monitor.yml`: inicialmente agendado para diagnóstico read-only; **agora sem cron redundante**, disponível para execução manual. Primeira execução **aprovada**: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39892381956. Recorrência do cron ainda não comprovada.
- `database/neon_imea_eligibilidade_motor.sql`: visão `nivon_imea_indicadores_verificados_v` criada no Neon. Quando há apenas `published_at` e `reference_date` é NULL, `analysis_eligibility=PUBLICACAO_SEM_REFERENCIA`, bloqueando promoção para tendência diária.
- O monitor de publicação não enviava valores ao Neon; agora o **workflow de ingestão OIDC separado** grava em staging (217 linhas), mas nenhum indicador IMEA pode ser apresentado como cotação de fechamento diária com base apenas na publicação.

## Implantação de ingestão comprovada — 22/10/2026 (America/Cuiaba)
- [Build do Neon](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894245964) compilou e testou o endpoint OIDC `/stage` (acesso sem token retorna HTTP 401).
- Função Neon `imeastage` implantada e ativa, consultando `public.nivon_imea_prices_staging`.
- [Primeira carga real](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894377921): **107 soja + 110 milho = 217 registros** gravados em staging, com `reference_date=NULL` e zero observações promovidas a cotações canônicas.
- [Segunda carga](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894495044): **217 duplicatas detectadas, zero inserções**; revisionamento por `source_key`/`version_hash`.
- [Workflow principal aprovado](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39894592868): consulta por GitHub OIDC confirmada na `main`, 217 duplicatas reconhecidas.
- Agenda `main/.github/workflows/imea-neon-stage.yml`: **14h e 23h UTC de segunda a sexta** (10h e 19h de Mato Grosso), com checkout pinado no commit testado `165ea961ffd36a17f4e718eaa400da1efe52dceb`. Ainda não houve observação de execução futura do cron.
- O monitor antigo `imea-publicacoes-monitor.yml` foi deixado como **diagnóstico manual**, sem cron redundante.
- `nivon_imea_staging_saude_v` acompanha os registros e a última execução real (tabela de logs), inclusive quando uma nova coleta não gera linhas novas.
- `nivon_p0_sources`: `ingest_state=ACTIVE`, `allow_automated_ingest=TRUE`, `freshness_state=PUBLICATION_ONLY`; `auth_state=PENDING_WRITTEN_PERMISSION` continua distinguindo autorização declarada pelo proprietário de comprovação documental do IMEA.
- Limitação importante: em staging há datas de **publicação**, não de referência de preço; nenhuma série IMEA deve ser tratada como preço físico de fechamento diário nem alimentar tendências sem homologação temporal.

## Próximas ações
1. Precisar/registrar condições da autorização: conjunto de indicadores, armazenamento privado, atualização automática, limite de chamadas, possibilidade de reuso analítico.
2. **Concluído:** transmissão autenticada OIDC de lotes validados para `nivon_imea_prices_staging`; iniciar observação de execução agendada e alertas de falha.
3. **Concluído em execuções consecutivas:** validação de idempotência `ON CONFLICT`. Pendente comprovar atualização em dias distintos e registrar revisões temporais reais quando ocorrerem.
4. Estender para algodão, boi e frete, respeitando unidade, praça, tempo de referência, safra e classificações.
5. Não promover candidatos para preço diário operacional nem motor de tendência antes de resolver `data_referencia` ou dispor de metodologia explícita para indicadores de publicação.
