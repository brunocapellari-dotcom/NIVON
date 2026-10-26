# NIVON — primeira comparação operacional das três modalidades (2025)

**Execução real em 25/10/2026, horário MT (26/10 UTC):**
https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40255162101 — **sucesso**, sem gravação GCP.

## O que ficou comprovado

- **ANTT/SIADE ferroviário:** base oficial, BigQuery, séries por estação de origem, com a auditoria independente dos anos 2006–ago/2026 já concluída.
- **ANTT/TRC rodoviário:** os 16 maiores fluxos anuais 2025, por RGI, sem NCM/produto; fonte oficial porém **não é a matriz completa de MDF-e**.
- **Hidrovia:** 27 grupos produto × trecho de hidrovia × sentido da réplica histórica 2025 do distribuidor HF `vinicius-souza/antaq`, revisão `ff0349fa6dc8cebcec161ee3ce48f6f73f7f3ba8`; lidos e auditados mas **TERCEIRO NÃO HOMOLOGADO**.

A execução combinou 9 polos terrestres e 27 grupos hidroviários **como três universos independentes**, com dados por origem, destino, mercadoria quando informada e proveniência.

### Recortes hidroviários da réplica, não aditivos

| Hidrovia | Produto | Sentido na fonte | Toneladas por trecho |
|---|---|---|---:|
| Madeira | soja | Desembarcados | 6.973.417,401 |
| Madeira | milho | Desembarcados | 3.060.004,434 |
| Tapajós | soja | Desembarcados | 7.584.978,210 |
| Tapajós | milho | Desembarcados | 7.271.125,931 |
| Baixo Amazonas | soja | Desembarcados | 10.728.159,507 |
| Baixo Amazonas | milho | Desembarcados | 9.293.593,476 |

**Não somar estes rios**: `Carga_Hidrovia` representa trechos, podendo repetir `IDCarga` ao longo da rota. Não supor que o volume de uma hidrovia equivale à carga embarcada em um terminal específico ou ao fluxo de caminhões para ele.

**Auditoria fonte terceira:**
- 2025: 92.431.869,759 toneladas associadas a navegação interior em `Carga` deduplicada por `IDCarga` na réplica (não valor oficial homologado).
- 53.250.176,855 toneladas dessas cargas interiores têm classificação de trecho de hidrovia na réplica; a cobertura por rio é parcial.
- 27 recortes agro por rio, sentido e produto passaram verificações de estrutura e de proveniência.
- SHA Carga_Hidrovia: `e02bc900f3450893670fa055027e085efa8e3ea86b0060a8534fcdabb475aba9`.
- SHA Carga: `5d3737ab69d4d26805ff69007cf4402bd59ebb5fb4d8e6b79782a1b435d42904`.
- Fonte HF revisada não mudou no monitor oficial:
  https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40254306816.

## Caminhos e gates

**Relatório JSON gerado pelo Actions**: workflow `.github/workflows/nivon-trimodal-2025-readonly.yml`; arquivo `nivon-trimodal-2025.json` no artifact da execução 40255162101, 90 dias de retenção.

**A ANTAQ migrou o link do painel para Aquarela** (a URL está no site oficial), que respondeu 200 mas forneceu apenas interface HTML Qlik; **não** comprovou microdados/API homologada. A sondagem está incorporada à automação diária **já existente** de monitoramento de fontes, sem criar nova tarefa.

A publicação da réplica de terceiros no BigQuery **ainda está bloqueada** por:
`NIVON_ANTAQ_REPLICA_WRITE_APPROVED`,
`NIVON_GCP_COST_REVIEWED` e
`NIVON_ANTAQ_REPLICA_BOOTSTRAP_APPROVED`, além de disparo manual confirmado.
O painel trimodal usa a réplica em memória efêmera do runner e **não** exige essas permissões de escrita.

A prova pontual trimodal passou a **workflow_dispatch sem acionamento por push** após sucesso. Nenhum dado GCP foi escrito nesse workflow.

**Próximo gate:** autenticar microdados primários da ANTAQ (ou exportação oficial comprovada do Aquarela) e obter matriz rodoviária MDF-e completa, sem deduplicar cargas entre modalidades por simples coincidência geográfica.
