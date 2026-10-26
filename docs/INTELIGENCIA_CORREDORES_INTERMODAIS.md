# NIVON — Inteligência de corredores logísticos por polo

O motor \`nivon.inteligencia_corredores\` acompanha fluxos MDF-e de origem e destino que **coincidem geograficamente** com municípios de polos ferroviários, hidroviários e portuários relevantes. O motor não atribui a transferência ao terminal nem presume passagem rodoviária exata pela rota.

## Polos iniciais

| Categoria | Polo municipal | Situação cadastral |
|---|---|---|
| Ferrovia | Rondonópolis/MT | Operacional |
| Ferrovia | Itiquira/MT | Operacional (referência) |
| Ferrovia | Dom Aquino/MT — Terminal BR-070 | Início em comissionamento 2026 |
| Ferrovia | Alto Araguaia/MT | Referência |
| Hidrovia | Itaituba/PA — Miritituba | Operacional |
| Hidrovia | Porto Velho/RO | Referência |
| Porto com acesso rodoviário/hidro | Santarém/PA | Operacional |
| Porto com acesso hidro/rodo | Barcarena/PA | Operacional |
| Porto com acesso hidro/rodo | Itacoatiara/AM | Referência |
| Porto multimodal | Santos/SP, Paranaguá/PR, Itaqui/MA, Rio Grande/RS e São Francisco do Sul/SC | Operacional |

**Status de infraestrutura NÃO é volume movimentado.** Terminal BR-070 iniciou comissionamento em junho de 2026, segundo a Ferrovia MT. O painel e os dados MDF-e não especificam necessariamente terminal usado.

Fontes de conferência: ANTT MDF-e/RNTRC; Rumo Malha Norte; Ferrovia MT Terminal 070; Hidrovias do Brasil; ANTAQ; operador Cargill Santarém (links nos objetos de polo).

## Operação

Requer banco SQLite previamente preenchido pelo importador \`scripts/ingest_antt_mdfe.py\`, cuja procedência deve ser homologada antes de uso analítico final.

\`\`\`bash
PYTHONPATH=src python scripts/corredores_antt_mdfe.py \
  --db /dados/nivon-antt.sqlite \
  --recorte universo_mt_2026_09 \
  --competencia 2026-09 \
  --limite 100 --somente-destino
\`\`\`

Saída JSON padronizada contém polo, origens, destinos, tonelagem no recorte, NCM, grupo do produto quando conhecido, categoria de transportador, nível (município/RGI), SHA do arquivo e data de coleta.

O ranking identifica **mercado potencial de captação rodoviária** para cada polo. Por exemplo, movimento com destino geográfico \`Rondonópolis\` é um potencial alimentador do polo ferroviário, mas pode ir a indústria, armazém ou distribuição sem utilizar a ferrovia.

## GATES de qualidade

1. \`RGI\` não é município, muito menos terminal. \`REGIAO_RGI_NAO_TERMINAL\` só permite polo regional potencial.
2. \`MUNICIPIO\` também não prova transbordo — somente presença do destino no município.
3. Produto \`NAO_IDENTIFICADO\` deve ficar sem imputação. NCM informado pode ser subconjunto amostral do MDF-e.
4. Quantidade de MDF-e NÃO equivale a viagens físicas. O indicador operacional é tonelagem no recorte.
5. **Recorte obrigatório**: não somar recortes de filtros sobrepostos, dois lotes/revisões da mesma base, fluxos de sentidos contrários, rodovia com ferrovia, rodovia com hidrovia ou porto com hidrovia sem chave de reconciliação e definição de etapa/modal.
6. Não presumir rota BR-163, BR-364, BR-070 ou número de quilômetros percorridos apenas pelos municípios OD. Rotas plausíveis requerem malha e modelagem identificada como estimativa.
7. A comparação com registros ferroviários SIADE (ANTT) e hidroviários/portuários (ANTAQ) deve ocorrer somente na granularidade, produto e período efetivamente disponíveis e com cuidado contra dupla contagem.

## Próximos conectores

- Camada ferroviária existente: \`nivon.transporte_multimodal\`, \`nivon.coleta_antt\` e \`nivon.antt_bigquery\`, da PR #140.
- Camada hidroviária ANTAQ ainda exige fonte primária e reconciliação; réplicas não devem virar observação canônica.
- Regras de referência portuária usam terminal específico e line-up/AIS quando possível, evitando confundir município com porto.
- O módulo não contém DB migrator nem cloud deployment: base pública completa de MDF-e por produto/município/mês segue dependente de publicação oficial estruturada (issue #142).

**Desenvolvimento e testes usam somente valores sintéticos; nenhuma tonelagem real foi gravada por este módulo.**

## Ranking agregado por polo

O JSON também expõe `resumo_polos`: toneladas por polo geográfico e **sentido separado** (entrada/saída), produtos identificados e até dez principais origens do polo, dentro do recorte único. O cálculo ocorre **antes** do limite de linhas do detalhamento, evitando ranking de polos truncado. Um polo de destino não representa necessariamente terminal utilizado. Os dados de municípios/regionais próximos mas distintos não são fundidos. Se a mesma carga aparecer posteriormente em ANTT SIADE e ANTAQ, essas observações permanecem em outras camadas, sem soma automática.
