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
