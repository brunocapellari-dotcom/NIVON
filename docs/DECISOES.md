# Registro de decisões — NIVON

Fonte de verdade para decisões do proprietário durante a reorganização. Registrar futuras alterações com data, autor e impacto; não confundir decisão com implementação concluída.

| Data | Decisão do proprietário | Consequência e estado |
|---|---|---|
| 25/10/2026 | Não utilizar Vercel no NIVON. | Google Cloud é o destino exclusivo de execução; remoção do legado é trabalho técnico **pendente**. |
| 26/10/2026 | Concentrar o NIVON em Google Cloud; GitHub para versionamento e gestão. | Sem frontends ou bancos paralelos como novas fontes canônicas. |
| 26/10/2026 | Retirar Neon como base de operação. | Migração e reconciliação com BigQuery **pendentes**; não desligar nem apagar dados sem autorização. |
| 26/10/2026 | CEPEA restrito ao uso interno autorizado. | Não redistribuir séries ou arquivos no repositório público; respeitar termos da fonte. |
| 26/10/2026 | Buscar operação com custo de **R$ 0**. | Meta, não garantia; quaisquer custos devem ser revisados e aprovados pelo proprietário. |
| 26/10/2026 | Repositório público somente com código e dados sintéticos, além de documentação publicável. | Não publicar credenciais, dados privados ou bases reais sem direitos de redistribuição. |
| 26/10/2026 | Reorganização em cinco frentes, Claude na direção técnica e Bruno nas decisões de merge e produção. | Fechamentos de PRs e exclusões de branches exigem `APROVADO`; execução segregada por arquivos. |
| 26/10/2026 | Alvo de simplificação: no máximo seis workflows, oito variáveis, um terminal IAP e um coletor Cloud Run Job. | Critérios-alvo até verificação da `main` e do ambiente, não estado atual. |

## Decisões futuras
Usar formato `AAAA-MM-DD — decisão — responsável — motivação — impactos — evidência/PR — status`. Nenhum plano de executor substitui autorização do proprietário.
