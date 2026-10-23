# NIVON — Entrega integrada: logística, marítimo e quantitativo (23/10/2026)

## Estado verificado e intenção

Esta entrega adiciona um **orquestrador analítico offline**, sem novo coletor,
sem novos datasets ou contas, sem Neon e sem gatilho de faturamento no Google Cloud.
Os insumos são snapshots gerados pelos módulos existentes. A análise é derivada,
sempre `SHADOW`, nunca automaticamente homologada. Testes usam exclusivamente
valores sintéticos, não comprovam que GCS/BigQuery foi executado em produção.

O estado real do NIVON na `main` em 23/10/2026 contém:
- MDF-e importado por recorte e ranking de polos em `inteligencia_corredores.py`;
- ANTT/SIADE ferroviário e verificações de fonte ANTAQ;
- `consulta_analitica_bq.py`, leitura temporal `as_of` de observações versionadas.
A reutilização do código avançado de AIS/line-up e dos anúncios de fretes
**ainda depende da consolidação dos PRs abertos**, sem conflito de versões.

## Um comando, três resultados isolados

```bash
python -m pip install -e .
python scripts/rodar_painel_operacional.py \
  --entrada tests/fixtures/painel_operacional_sintetico.json \
  --as-of 2026-10-23T12:00:00Z
```

A estrutura de entrada é um JSON com três chaves opcionais:
- `corredores`: saída íntegra de `consultar_corredores` (MDF-e; mesmo recorte);
- `portos`: snapshots AIS por porto com MMSI deduplicado, validação de
  geocercas, reconciliação física/operacional e **histórico do mesmo porto**;
- `series`: coleções de `observacoes` conforme contrato da consulta BigQuery,
  com `campos.serie_id`, `campos.classe` e as condições de comparação.

Todos os preços têm `data_referencia`, `data_publicacao`,
`data_coleta`, `identidade`, `valor`, `unidade`, `natureza` e
`campos`. Condições de transportadora, equipamento, regime, terminal,
origem, destino, produto e contrato não podem divergir dentro da mesma série.
Para `FRETE_ANUNCIADO`, apenas valores divulgados pela mesma transportadora
e condições entram na série; o maior anúncio do dia é usado, sem assumir
que é o mais recente ou foi efetivamente negociado. Para `CBOT`, o
contrato futuro é obrigatório. Observações sem publicação temporal verificável
ou coletadas/publicadas depois do instante consultado ficam de fora.

A tendência `ALTA/BAIXA/ESTABILIDADE` é uma classificação
**heurística das medianas em duas metades**, exige no mínimo seis dias
em ao menos sete dias de intervalo e frescor de referência, não uma
probabilidade calibrada. Ausência de dados é ausência, não preço zero.

No mar, o índice AIS provisório compara navios aguardando com 30+ pontos
do mesmo porto e exige geocercas validadas, MMSI únicos, conciliação
AIS×operação de pelo menos 95% e snapshot de até seis horas. Line-up
CDP não validado é apresentado como **não confiável** e jamais entra
no índice; mesmo um line-up validado só aparece como contexto. Nem
presença AIS no berço nem programação tornam um navio `OPERADO` ou
confirmam carga, tonelagem, DUV ou terminal contratado.

O bloco de corredores preserva o ranking do **único recorte** MDF-e.
Nunca soma MDF-e + TU ferroviárias + ANTAQ, nunca divide volumes
sem compatibilizar universo e período e nunca converte o município
de destino em um terminal de transbordo confirmado.

## Integração com Google Cloud sem duplicar pipelines

A tabela historizada e o loader existente continuam sendo a via principal:
coletor → RAW com SHA-256 no GCS → observação versionada no BigQuery
→ `consulta_analitica_bq.consultar(..., as_of=..., executar=True)`
→ adaptação explícita das observações ao pacote acima → motor → saída shadow.

Na ausência de fonte real, o motor retorna `DADOS_INSUFICIENTES`.
Este PR **não** cria cargas GCS/BQ, não executa Cloud Run ou cron,
não aciona coleta AIS/line-up, não publica sinais nem altera IAM.

## Prioridades de execução e testes em lote

| Gate | Tarefa de engenharia | Prova necessária |
|---|---|---|
| P0 | CI offline do novo contrato, CLI E2E em um único job | Três resultados num lote, bloqueios de tempo, MMSI, geocerca, frete e universo |
| P0 | Convergir PR #166 de estação ANTT com a `main` | TU por estação, MDF-e por município, sem alegação de transbordo |
| P0 | Consolidar PR #141 (AIS, line-ups CDP, reconciliação) e #150 (PDF isolado) | Backfill, escala/DUV quando confirmado, revisão as-of, segurança PDF |
| P0 | Consolidar PR #154/#146 (ledger fretes) e #82 (pareamento) | Sem duplicar anúncios, sem trocar condições/transportadoras, sem falsos movimentos |
| P1 | Adaptadores de saída das três famílias para o contrato do painel | BigQuery as-of real e rastreável + RAW/GCS verificado |
| P1 | Efetivar fontes por porto: Santos, Paranaguá, Itaqui, Rio Grande, Santarém, Vila do Conde, Itacoatiara, Suape, Imbituba, Ponta da Madeira | Linha de vida de escala por DUV quando existente, divergência CDP registrada; Amaggi Itacoatiara somente inferido por AIS |
| P2 | Baseline probabilístico de filas/ETA e tendências de frete/CBOT/físico | Backtests walk-forward point-in-time, erro MAE/calibração, comparação com baseline e intervalos empíricos |
| P2 | Promover indicadores após auditoria independente | Cobertura, frescor, performance fora da amostra, observabilidade, licença/custo e aprovação editorial |

**Não considerar concluídas** tarefas desta tabela só por estarem descritas.
A execução contínua depende de merges e credenciais/gates GCP que já existem
na governança do projeto e não são ampliados nesta entrega.
