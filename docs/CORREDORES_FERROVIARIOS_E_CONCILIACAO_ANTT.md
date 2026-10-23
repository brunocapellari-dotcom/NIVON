# NIVON — Ranking ferroviário ANTT/SIADE por estação e produto

## Objetivo

Aproveitar a base **real** de produção ferroviária origem–destino da ANTT/SIADE (CSV anual com dados mensais, TU e TKU) para distinguir polos de embarque ferroviário, mercadorias, estações de destino, sazonalidade e possíveis relações com regiões de chegada de cargas rodoviárias.

- **Nível confirmado pela fonte:** estação ferroviária de origem, estação de destino, ferrovia, mercadoria ANTT, UF, competência, toneladas úteis TU.
- **Vínculo municipal proposto:** nome de estação exatamente igual ao município de um polo ferroviário catalogado. Essa associação é apenas **hipótese geográfica**, não comprovação de terminal específico.
- **Relação com rodovia:** exibir lado a lado chegadas rodoviárias ao município/à RGI e saídas ferroviárias de estação por mês, jamais somar, dividir, subtrair ou concluir transbordo físico sem chaves adicionais.
- Não usar o calendário de comissionamento de Dom Aquino como prova de cargas efetivas. A ausência de registro SIADE (inclusive linhas sob autorização estadual) não prova volume zero.
- NCM rodoviário por definição do MDF-e, mercadoria ferroviária por nomenclatura ANTT. Taxonomia genérica só recebe correspondência em casos textuais exatos; resto fica sem mapeamento.

## Fluxo executável

Os coletores existentes \`nivon.coleta_antt\`, \`nivon.antt_bigquery\` são reutilizados: o motor consome \`montar_lote()\`, que releitura bruto e reconcilia manifesto, SHA-256, competência e registros. Nenhuma segunda via de ingestão é criada.

\`\`\`bash
PYTHONPATH=src python -m nivon.coleta_antt \
  --inicio 2025 --fim 2026 --destino /dados/antt-staging --live

PYTHONPATH=src python scripts/ranking_ferrovias_antt.py \
  --staging /dados/antt-staging --ano 2026 \
  --competencia 2026-08 --uf-origem MT --limite 30

# Quando houver exportação rodoviária autenticada:
PYTHONPATH=src python scripts/ranking_ferrovias_antt.py \
  --staging /dados/antt-staging --ano 2026 \
  --competencia 2026-08 \
  --banco-rodo /dados/antt-mdfe.sqlite \
  --recorte-rodo mt_agosto_2026
\`\`\`

Os campos de saída incluem SHA-256 da fonte, competência, estação de origem, mercadoria **literal** da ANTT, destino ferroviário, TU, classificação de qualidade e polos candidatos por nome exato. O quadro intermodal preserva \`rodoviario_estado\` e explicitamente proíbe soma ou razão entre modais, salvo futura homologação com transbordo real.

## Teste E2E e continuidade

O workflow \`nivon-corredores-ferroviarios.yml\` executa testes offline e um smoke **read-only** de fontes ANTT 2025/2026. Gera relatórios resumidos como artefatos do GitHub, sem publicar arquivos brutos. É prova de consulta (não é BigQuery, nem dataset persistente).

As seguintes validações serão necessárias antes de qualificar as comparações por polo como operacionais:
1. Homologar estação da ANTT contra cadastro de terminais, código de estação, localização e ferrovia.
2. Separar fluxo ferroviário **embarcado** de outras passagens/ajustes de TU e definir granularidade de produto.
3. Cruzar dados primários de movimentação de terminais quando disponíveis, sem misturar saldo físico com TU em múltiplas pernas.
4. Integrar SIADE ao BigQuery com WIF/dataset/bucket autorizados; execução Cloud ainda não confirmada.
5. Para rodovia, homologar produto/NCM, granularidade de origem/destino e série MDF-e completa; abrir #142.

Fonte: https://www.gov.br/antt/pt-br/assuntos/ferrovias/dados-de-producao-do-transporte-de-carga-origem-destino


## Evidência live 23/10/2026 — ranking de estações MT

Execução sem credenciais com origem de dados ANTT/SIADE confirmada:
https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39952301139

| Estação origem | Ago/2025 TU | Ago/2026 TU | Variação interanual |
|---|---:|---:|---:|
| Rondonópolis | 2.159.788 | 2.223.328 | +2,94% |
| Itiquira | 73.940 | 50.584 | −31,59% |
| Alto Araguaia | 120.759 | 112.414 | −6,91% |

- Arquivo 2025 SHA-256 \`265a40f1759fcb6af5a83d28b687d3621d8cf50054ae777f80e7cb0d9e863114\`.
- Arquivo 2026 SHA-256 \`d5063b8f5af64e358bb02fe9189079839b09e765e288e7ce49fdaf30e196f1f8\` (até 2026-08 no arquivo verificado).
- O município de Dom Aquino não apresentou **correspondência exata de estação na fonte SIADE deste recorte**; jamais publicar volume zero, pois a ferrovia estadual pode ter cobertura distinta.
- A fonte usa \`Grãos - Milho\` para milho. Crosswalk atualizado com esta denominação literal, sem alteração retroativa de campos canônicos.
- As medições são **TONELADAS ÚTEIS FERROVIÁRIAS**, não volume rodoviário, movimentação portuária ou carga fisicamente única de toda a cadeia.
- Revisões futuras do CSV exigem reprocessamento por hash e podem alterar os valores divulgados acima.
