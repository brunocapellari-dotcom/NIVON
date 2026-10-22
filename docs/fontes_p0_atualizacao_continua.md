# NIVON — fontes P0 com atualização recorrente (22/10/2026)

## Princípio vinculante
**Drive é arquivo histórico, NÃO fonte de preços atuais.** O valor mais recente deve vir da própria CEPEA, IMEA ou CONAB, sob direitos de uso validados. A data de coleta não substitui competência, data de cotação ou publicação. Motores só podem rotular uma série como atual quando houver fonte original, referência recente e pipeline funcional. Revisões do passado são preservadas, não sobrescritas.

## Estado comprovado

| Fonte | Direitos | Coleta real | Banco no Neon | Recorrência |
|---|---|---|---|---|
| CEPEA | CC BY-NC 4.0 (uso pessoal não comercial e atribuição) | Soja Paranaguá e Paraná pelo site oficial; 30 observações | Sim, `nivon_cepea_prices` | Workflow no **main** `cepea-neon-ingest.yml`, cron `30 21 * * 1-5` UTC; primeira execução main concluída com 30 duplicatas e zero inserções, provando persistência idempotente. Execução futura por cron ainda não observada. |
| CONAB | Dados públicos oficiais com proveniência | Soja/milho MT: dois levantamentos, 2010–2025, balanços | Sim, 4 estimativas + 32 séries históricas + 14 balanços | Workflow OIDC validado por push no **branch feature**; cron apenas efetivo quando fluxo principal estiver homologado. **Não afirmar produção diária em main**. |
| IMEA | Aguardando confirmação documental para coleta e armazenamento automatizados | Não homologada | Apenas inventário histórico do Drive, sem cotações promovidas | **Bloqueada por direitos.** Preparado pedido de autorização, ainda não enviado. |

## Evidências ao vivo
- CEPEA coleta direta oficial com parser isolado, sem Notícias Agrícolas: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39855374825
- CEPEA ingestão OIDC Neon com 30 novas observações: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39856137721
- CEPEA **primeira execução na main**, 30 duplicatas corretamente evitadas: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39856413420
- CONAB coleta e histórico 2010–2025: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39702302650
- CONAB segunda execução histórica: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39702649991

## Inventário do Google Drive (metadados, sem ingestão dos bytes)
- `CEPEA`: 1 arquivo ZIP, 175.296.628 bytes, última modificação 07/08/2026.
- `IMEA`: 4 arquivos, contendo planilha consolidada e ZIPs de soja, milho, algodão, últimas modificações 07–10/08/2026.
- `CONAB`: 16 arquivos: 15 ZIPs e 1 XLSX, últimas modificações 07–10/08/2026.
- Total: **21 arquivos registrados** em `nivon_p0_drive_inventory`, com `promoted_to_current=FALSE`. Conteúdo ainda não foi copiado para o banco operacional.
- Amostra de esquema da planilha consolidada IMEA: `DATA, SEMANA, MÊS, ANO, PRODUTO, INFORMAÇÃO, LOCAL, UNIDADE, FONTE, DADO, INFORMAÇÃO_FONTE`. **Não autorizar a importação só porque a planilha está acessível**. A licença é independente do acesso e datas de referência antigas não constituem atualização.

## Estruturas analíticas e governança
- `nivon_p0_sources`: direito de uso, estado do conector, cadence, última verificação.
- `nivon_p0_source_checks`: execuções, novas observações, erros, SOURCE_LAG.
- `nivon_p0_drive_inventory`: metadados imutáveis do acervo com selo histórico.
- `nivon_p0_frescor`: fonte, idade da última observação e condição operacional, sem usar modifiedTime do Drive.
- `nivon_cepea_prices`: preço por série, praça, saca 60kg, referência e revisão.
- `nivon_cepea_variacao_diaria_v`: mudança porcentual **descritiva** dia a dia, não projeção.
- `nivon_conab_producao_anual_v`: variação interanual **histórica**, sem confundir com preço físico.
- Fontes oficiais CEPEA com CC BY-NC: https://cepea.org.br/br/licenca-de-uso-de-dados.aspx
- Termo oficial do IMEA: https://imea.com.br/imea-site/termo-de-uso.html
- Safras oficiais CONAB: https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras

## Pendências que não podem ser declaradas prontas
1. Confirmar segunda data de execução do agendamento CEPEA em main e instrumentar alertas de falhas / atraso.
2. Habilitar agendamento CONAB em main após reconciliação de workflow, testes de integração e segurança; não usar PR draft como fonte permanente de execução.
3. IMEA: encaminhar o pedido formal de autorização; após recebimento, homologar atualização automatizada diária/semanal de preços regionais, fretes e comercialização sem violar termos.
4. Ampliar o CEPEA para milho e outras culturas só após teste em fonte original, identificação de séries e licença.
5. Auditar/adaptar histórico do Drive por documento/lote, em quarentena, reconciliando com dados de origem e revisões antes da promoção à base canônica.
6. Backup externo, alertas de pipeline e controle de quotas gratuitos.

## Critério mínimo de aceite por fonte
Cada atualização exige URL de origem, data de referência, data de coleta, praça/UF, unidade, código de série, licença, parser, log de execução, ausência de duplicação, tratamento de erro e teste no banco. A ausência de nova cotação não equivale automaticamente a falha; uma coleta falha jamais pode exibir preço antigo como novo.
