# Radar operacional de metadados (#291)

`nivon.fontes_radar.radar(eventos, politicas, agora=...)` é uma função pura para
ANTT, CEPEA, IMEA e CONAB. Não consulta fontes, lê dados de preços, executa SQL,
grava staging ou modifica estado de homologação. Reutiliza a avaliação de saúde
de transporte já existente em `maritime_source_health`, sem alterar esse módulo.

Entrada é uma projeção de metadados de readbacks já autorizados, não um coletor.
Cada evento tem `fonte`, `evento_id` único e imutável por evento de coleta,
`estado` (`NORMALIZED`, `QUARANTINED` ou `UNAVAILABLE`) e `data_coleta` com fuso.
Eventos normalizados têm `data_referencia` ISO, `competencia` YYYY-MM opcional
coerente com a referência e `data_publicacao` opcional. Datas sem horário são
preservadas como datas, sem afirmar instante de publicação. Data de publicação
não substitui referência agrícola; safra sem mapeamento permanece em quarentena.

Cada política informa `homologada` (derivada de revisão existente, nunca por
inferência), `limite_defasagem_dias` e `intervalo_coleta_minutos`. Não há SLA de
fonte inventado ou limiar padrão: valores precisam ser definidos pelo responsável
da fonte. Homologação ausente ou evento em QUARANTINED resulta em `quarantined`.
O radar não concede licença, redistribuição ou promoção mesmo quando `fresh`.

Estados:

- `fresh`: metadados normalizados na janela explícita e coletor saudável.
- `lagged`: referência além do limite, mesmo que a coleta seja recente.
- `unavailable`: sem metadados, erro mais recente, coletor atrasado ou contrato inválido.
- `quarantined`: revisão/homologação pendente; não promover automaticamente.

Duplicata idêntica é idempotente. Mesmo ID com conteúdo divergente bloqueia a
fonte. IDs distintos com mesma referência sinalizam revisão, sem rejuvenescer a
referência. A última referência prevalece sobre backfill mais antigo; a coleta da
observação e `ultima_coleta_fonte` são distintas quando necessário. Ausências são
null, inclusive publicação desconhecida e quantidade de eventos inexistentes.

## JSON para consumo pelo painel

```sh
python -B -m nivon.fontes_radar --entrada /privado/metadados.json --agora 2026-10-25T20:30:00+00:00
```

O arquivo contém `eventos` e `politicas` no formato acima. Saída tem schema
`nivon.fontes.radar.v1`, os quatro estados, timestamps, competência e causa.
Relógio explícito torna a avaliação reproduzível. O painel pode consumir essa
saída sem aumentar queries: esta entrega disponibiliza o JSON, não ativa polling,
cron, leitura GCP ou ingestão restrita. Metadados ainda não fornecidos permanecem
indisponíveis. Nenhuma série real foi homologada por esta implementação.
