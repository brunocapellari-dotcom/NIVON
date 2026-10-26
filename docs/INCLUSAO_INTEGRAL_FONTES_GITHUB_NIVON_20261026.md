# NIVON — Inclusão integral do levantamento GitHub (26/10/2026)

## Decisão e fonte única

Todo o conjunto relevante da pesquisa foi incorporado **ao projeto NIVON**, não a outra aplicação.

**Inventário canônico, legível por programas:**
`config/catalogo_integracoes_github_20261026.json`

**Consulta interna:**
`python -m nivon.catalogo_github`

O inventário registra **33 repositórios e 55 datasets do agrobr 2.0.0**, explicitando status, destino e restrições. Nenhum repositório de terceiros foi clonado sem necessidade. O código próprio do NIVON continua canônico; bibliotecas licenciadas são dependências ou referências, conforme a utilidade real.

## Incorporação no código

| Fonte/dataset | Código NIVON | Natureza da inclusão |
|---|---|---|
| ANP PPI (4 combustíveis) | `src/nivon/anp_ppi.py` | Já incorporado anteriormente à main |
| MDIC/Comex Stat — exportação | `src/nivon/agrobr_mercados.py` | Já incorporado anteriormente à main |
| MDIC/Comex Stat — importação | `src/nivon/agrobr_mercados.py` | Já incorporado anteriormente à main |
| CFTC — COT semanal | `src/nivon/agrobr_mercados.py` | Já incorporado anteriormente à main |
| IBGE PPM — rebanhos e origem animal | `src/nivon/agrobr_setoriais.py` | Adaptador acrescentado, ainda não testado |
| IBGE Abate — bovino, suíno, frango | `src/nivon/agrobr_setoriais.py` | Adaptador acrescentado, ainda não testado |
| IBGE Leite — aquisição/industrialização | `src/nivon/agrobr_setoriais.py` | Adaptador acrescentado, ainda não testado |
| IBGE PAM — produção agrícola anual | `src/nivon/agrobr_setoriais.py` | Adaptador acrescentado, ainda não testado |
| ANP — diesel de revenda (não confundir com PPI) | `src/nivon/agrobr_setoriais.py` | Adaptador acrescentado, ainda não testado |
| IBGE — PIB agropecuário | `src/nivon/agrobr_setoriais.py` | Adaptador acrescentado, ainda não testado |
| CONAB progresso e revisões | `src/nivon/conab_agrobr.py` e módulos atuais CONAB | Reutilizar o existente e reconciliar PRs abertas |
| ANA/INMET/AIS/BCB/PTAX/ANTT/ANTAQ | Módulos existentes em `src/nivon` | Não criar coletores paralelos |

**Outras 45 famílias do agrobr** ficam registradas e classificadas, inclusive as de frete portuário, clima, fertilizantes, soja, B3, USDA PSD, crédito rural, safra, MapBiomas e CFTC. As que não foram contempladas pelas interfaces de coleta acima são possibilidades para execução posterior, **não coletores operacionais disfarçados de entregas completas**.

## Regras de fonte

- Uso de `agrobr==2.0.0` já declarado no NIVON, com `return_meta=True` para proveniência, contrato, licença e fonte efetivamente selecionada.
- Quando a fonte fizer fallback, a fonte de fato deve ser declarada. Quando os termos/contrato não permitirem, bloquear por padrão; não converter dados CEPEA/ANEC/ANDA/B3 de regime desconhecido em dados de livre uso.
- Os registros normalizados originados de uma biblioteca são **snapshots derivativos**, nunca bytes originais dos servidores oficiais. Separar hash downstream de hash original upstream quando informado.
- Identidades, datas e unidades próprias para cada série. Datas anuais e trimestrais usam fim do período como **chave convencional no ledger**, e não como suposta data da observação.
- PPI diesel é preço de paridade sem tributos; o diesel ANP de revenda mede outra etapa do mercado. Nenhum deles isoladamente é frete realizado.
- O CSV/JSONL preparado para o BigQuery deve passar pela mesma camada `src/nivon/carga_bigquery_fontes.py`. Não gerar novos projetos GCP, tabelas ou serviços por iniciativa isolada.
- Versões existentes de CONAB, CEPEA, IMEA, AIS, INMET, ANA e ANP continuam sendo responsabilidades dos módulos/PRs já identificados. Não fazer merge em massa de PRs antigas para simular integração completa.
- Referências sem licença explícita e componentes GPL/AGPL são **inventariados, não copiados** para o código proprietário do NIVON.

## Uso previsto dos adaptadores acrescentados

**Estes comandos estão registrados para execução futura. Não foram executados nem homologados nesta entrega.** Exigem infraestrutura/ambiente NIVON existente e extra `agro`, já previsto no projeto.

```bash
python -m nivon.catalogo_github --secao repositorios
python -m nivon.catalogo_github --secao datasets_agrobr_2_0
python -m nivon.agrobr_setoriais --dataset pecuaria_municipal --produto bovino --ano 2025 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_setoriais --dataset abate_trimestral --produto bovino --trimestre 202602 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_setoriais --dataset leite_industrial --trimestre 202602 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_setoriais --dataset producao_anual --produto soja --ano 2025 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_setoriais --dataset precos_diesel --produto "DIESEL S10" --inicio 2026-09-01 --fim 2026-10-01 --uf MT --executar --exportar-jsonl
python -m nivon.agrobr_setoriais --dataset pib_agro --produto agropecuaria --trimestre 202602 --executar --exportar-jsonl
```

As consultas são delimitadas, opt-in e não disparam Cloud Run, BigQuery ou horários recorrentes. O operador `agrobr_mercados.py` permanece responsável por Comex Stat e CFTC para evitar duplicidade.

## Decisão sobre testes e lançamento

**Por decisão explícita do proprietário em 26/10/2026: nesta entrega, NÃO executar nem criar novos testes.** A etapa de teste está adiada, e não dispensada.

- Status do catálogo: **ARQUIVOS INCORPORADOS AO GITHUB**.
- Status dos seis novos adaptadores: **CÓDIGO INCLUÍDO / NÃO TESTADO / NÃO HOMOLOGADO**.
- Status coleta real IBGE/ANP pelo novo adaptador: **NÃO VERIFICADA**.
- Status dos 55 datasets: **CATALOGADOS** (não equivale a todos coletados).
- Status GCP/BigQuery: **SEM NOVA CARGA NESTA ENTREGA**.
- Status terminal: **SEM NOVA PUBLICAÇÃO NESTA ENTREGA**.

A consolidação posterior precisa conciliar contratos/dados reais, direitos, idempotência e GCP antes de declarar disponibilidade operacional. Nenhuma configuração nova deve ser solicitada ao proprietário por rotina enquanto puder ser resolvida no próprio projeto.
