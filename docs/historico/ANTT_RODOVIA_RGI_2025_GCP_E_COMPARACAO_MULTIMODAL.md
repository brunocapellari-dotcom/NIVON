# NIVON — primeira carga rodoviária real e comparação RGI × ferrovia (23/10/2026)

## Evidências operacionais

- **Fonte oficial:** Anuário TRC 2025, Tabela 12, ANTT: https://www.gov.br/antt/pt-br/assuntos/cargas/dadostrc/anuario_trc_2025_antt.pdf
- **Carga oficial GCS + BQ conciliada:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40009540542 — success.
- **Comparação de 2025 rodovia e ferrovia, sem soma:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40010743069 — success.
- **Fonte ferroviária 2006–ago/2026 reconciliada:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001461762 — success.

### Persistência rodoviária

- Projeto: nivon-data
- Dataset: nivon_raw; região: southamerica-east1
- Bucket imutável por SHA: nivon-data-raw-2026
- Tabela: nivon-data.nivon_raw.antt_rodovia_rgi_top16_snapshots
- View atual: nivon-data.nivon_raw.vw_antt_rodovia_rgi_top16_atual
- Anuário: 2025, 16 fluxos anuais de RGIs em todo Brasil, **98.170.287 t somadas SOMENTE nesse subconjunto**; não são toneladas de um recorte completo da movimentação rodoviária nacional.
- PDF real: 3.994.007 bytes; SHA-256 **db96f4a5e779261a28e050b165ef84236ddd92d3ac0f0801a12fb04306e03e0b**.
- Registros: 16, conferidos por COUNT e SUM(toneladas) no BigQuery após a carga.
- Documento classificado como `OBSERVADO_RELATORIO_OFICIAL_TOP16`. Competência 2025, referência 31/12/2025; data exata de publicação não autenticada e fica NULL.
- Produto/NCM não informado no recorte e não pode ser inferido. RGI é uma região e não corresponde necessariamente aos limites de município, porto ou terminal. A tabela da ANTT não constitui matriz mensal integral de MDF-e/RNTRC.

### Principais fluxos relevantes para MT — Tabela 12 oficial, 2025

| Origem RGI | Destino RGI | Toneladas do recorte |
|---|---|---:|
| MT / Rondonópolis | MT / Sorriso | 9.946.350 |
| MT / Sorriso | MT / Sorriso | 8.478.820 |
| PA / Itaituba | MT / Sinop | 6.350.618 |
| MT / Rondonópolis | MT / Primavera do Leste | 4.677.980 |
| MT / Sorriso | MT / Cuiabá | 4.287.972 |
| PA / Itaituba | MT / Sorriso | 4.243.478 |
| MT / Rondonópolis | MT / Rondonópolis | 3.631.841 |

É a direção origem→destino **tal como declarada na tabela do relatório**, inclusive nas rotas que pareçam contraintuitivas. Não inverter para transformar um fluxo em alimentação do terminal. Um fluxo com origem/destino na mesma RGI pode incluir deslocamentos entre municípios da região; não descreve necessariamente frete municipal interno.

### Polo ferroviário de Rondonópolis, recorte distinto

Na view da ANTT/SIADE ferroviária, a **estação de origem de Rondonópolis** movimentou em 2025: **24.258.027 toneladas úteis**. Itiquira: **742.649 TU**; Alto Araguaia: **1.458.596 TU**. Esses registros representam transporte ferroviário por estação e produto e **não podem ser somados** aos fluxos anuais de RGIs rodoviárias para produzir um total multimodal único, pois cobertura, granularidade, direções e universo são distintos.

A comparação read-only no Google Cloud gerou **9 polos** no catálogo, com **2 polos** que tiveram pelo menos um fluxo rodoviário top-16 coincidente por nome de RGI: Rondonópolis e Itaituba (Miritituba). Match geográfico não prova operação no terminal. Dom Aquino, Itiquira e demais polos sem RGI correspondente nos 16 maiores fluxos devem ser classificados como **sem observação nesse subconjunto**, jamais zero transporte.

### Hidrovia e portos

O portal de microdados do Estatístico Aquaviário da ANTAQ redirecionava para aviso de indisponibilidade no momento da consulta de 23/10/2026. Fonte da indisponibilidade: https://estatistica.antaq.gov.br/ea/sense/download.html

Existe uma réplica terceira de 2025 inspecionada e documentada em docs/ANTAQ_REPLICA_CARGAS_HIDROVIAS_2025.md; ela não está homologada nem carregada como fonte oficial na camada primária BigQuery. Dados por segmento de hidrovia podem conter o mesmo IDCarga repetido; somar rios, ferrovias e rodovias gera risco de dupla contagem.

### Regras operacionais

1. Preservar origem, granularidade, escopo e SHA distintos para cada modal.
2. Não inserir produtos ou NCM quando ausentes na RGI do anuário.
3. Não concluir transbordos reais entre caminhões, ferrovia e balsas por simples igualdade de nomes ou proximidade geográfica.
4. Não confundir tonelagem observada com viagens físicas, frete anunciado ou frete efetivamente negociado.
5. O workflow de primeira carga rodoviária e o de comparação foram transformados em **acionamento manual**, sem push nem cron, após a prova. Isso evita novas consultas e cargas pagas por alterações de código. Custos efetivos de GCP precisam ser conferidos em Billing, e byte limits não são garantia de custo zero.

**Próxima necessidade material:** matriz MDF-e OD oficial mensal e por NCM/mercadoria (issue #142), ANTAQ primária novamente acessível, reconciliação de instalações de transbordo com uma chave de correspondência comprovada e verificação de faturamento por execução.
