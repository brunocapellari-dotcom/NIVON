# NIVON — Arquitetura canônica de coletores, APIs e indicadores

**Versão:** 1.0 — 19/10/2026. **GO documental, NÃO GO-LIVE operacional.**

A fonte única de verdade é `config/fontes_nivon_master.v1.json`, validada por `src/nivon/catalogo_fontes.py`; a cobertura de produtos é mantida em `config/matriz_produtos_indicadores.v1.json`. Estes arquivos ORGANIZAM fontes e dependências; não concedem licença de dados, não executam scraping e não garantem que exista API gratuita.

## 1. Inventário inicial por estágio

- **59 fontes identificadas**, cada uma com identificador, provedor, URL de referência, acesso e situação jurídica.
- **86 datasets**: 25 P0 (nucleares), 42 P1 (complementares) e 19 P2 (aprofundamento).
- **15 grupos de informações, 16 frentes de inteligência e 132 indicadores previstos**, com 118 vínculos a datasets.
- **2 snapshots reais testados**: MAPA/SIPEAGRO fabricantes e CONAB grãos soja/milho; este estágio não implica operação recorrente homologada.
- **4 componentes com código existente**, mas sem comprovação suficiente de homologação real neste catálogo: ANP diesel de revenda, ANTT ferrovia e adaptador MDIC NCM (exportação, offline).
- **32 datasets no estágio apenas descoberta**, 35 candidatos para adaptação e 13 bloqueados por direitos.
- **Nenhuma das 86 coletas está habilitada para agendamento automático** nesta versão.

Os estados descrevem a **maturidade de coleta do dataset**, não a qualidade de toda a organização que o publica. A URL cadastrada é uma página/recurso de referência; somente depois de descobrir e testar o endpoint e a modalidade específica ele poderá ser usado em produção.

## 2. Contrato único de integração

Cada dataset passa por:

```
CATÁLOGO CANÔNICO
  → Direitos por OPERAÇÃO (consulta, coleta, armazenamento, transformação, envio e redistribuição)
  → Descoberta autorizada de endpoint, arquivo ou página
  → Aquisição com timeout, host allowlist, rate limit, MIME e tamanho máximos
  → Hash do bruto + snapshot/vintage + licença e URL da edição
  → Parser com schema estrito, codificação, unidades e classificação
  → Normalização por identificadores IBGE, NCM, UF, produto, safra e período
  → Controle temporal: competência, referência, publicação, coleta
  → Validação independente de conservação, plausibilidade, coverage, deduplicação
  → Persistência incremental + backup/restore + histórico as-of
  → Exposição em indicadores, relatórios, API e briefing com freshness e evidencia
```

Campos mínimos obrigatórios: `source_id`, `dataset_id`, `source_url`, `source_license`, `source_operation`, `content_sha256`, `schema_version`, `vintage_id`, `product_id`, `region_id`, `metric_id`, `unit_id`, `value`, `competencia`, `referencia`, `publicacao`, `coleta`, `observational_kind`, `quality_status`. Quando a publicação não possui data, registrar `NULL` e marcar a restrição temporal — **nunca inventar data**. A coleta não serve como substituta da publicação.

**Padrão de aquisição recomendado:** API oficial quando documentada, arquivos públicos estruturados como segunda via, HTML/PDF oficial com fixtures de layout como terceira; importação autorizada manual quando API e download não estiverem disponíveis; fonte paga/restrita permanece OFF.

## 3. Onde cada coletor entra

| Frente | Bases prioritárias | Situação atual / observação |
|---|---|---|
| Produção, área, produtividade | CONAB, IBGE/SIDRA, USDA | CONAB soja/milho com XLS testados; algodão, trigo, sorgo, açúcar e demais requerem adaptadores |
| Balanço e demanda | CONAB, USDA PSD, ABIOVE, Sindirações | Dados oficiais e consultorias não podem ser somados cegamente; ração e esmagamento são parcelas |
| Fábricas de ração e fertilizante | SIPEAGRO/MAPA | Cadastro de ração agregado por município obtido; **não comprova capacidade, consumo ou comprador** |
| Gado e bezerro | IBGE PPM/abate, CEPEA/IMEA/Scot | Mercado físico licenciado ainda sem autorização de captura/redistribuição |
| Etanol, açúcar e milho industrial | ANP, UNICA, CONAB, CEPEA | Coeficientes CEPEA de margem, etanol separado por matéria-prima/tipo |
| Diesel e petróleo | ANP revenda/produtor, MDIC, EIA, BCB | Código de diesel revenda presente; paridade Diesel A/B, biodiesel b(t), imposto e frete ainda por integrar |
| Fertilizantes | MDIC, ANDA, MAPA, ANTAQ, World Bank | Dados separados em importado, produzido, entregue, estoque e descargas |
| Comércio exterior | MDIC Comex Stat, USDA, UN Comtrade | Adaptador offline de exportações NCM/UF implementado com testes sintéticos; importação e CSV real pendentes. NCM/UF/via/URF não equivale a município SH4 |
| Transporte rodoviário | ANTT MDF-e/RNTRC | NCM parcial, destino potencial e terminal; export automático do painel ainda não homologado |
| Ferrovia e terminais | ANTT SIADE, ONTL | TU/TKU por estação; estação não equivale ao destino do produto |
| Movimento realizado de portos | ANTAQ | Dados agregados de movimentação não equivalem a line-up por navio |
| Line-ups brasileiros | 10 autoridades/terminais | Dez cadastrados, **nenhum porto homologado real**; Tubarão requer solução de acesso legítima |
| Internacional e AIS | MPA Singapore, Rotterdam, USACE, AIS autorizado | Dados históricos/estatísticos ou acesso por contrato; AIS não prova carga |
| Clima e hidrologia | INMET, CPTEC, NOAA, ECMWF, ANA, ZARC | Observado, previsão, projeção e níveis hidrológicos guardados em séries separadas |
| Mercado, câmbio e bolsas | BCB, CEPEA, IMEA, B3, CME, ICE | PTAX/SGS têm possibilidade de API; market data comercial fica bloqueado |
| Notícias e geopolítica | Fontes oficiais, Notícias Agrícolas, Reuters, Agroclima | Autorização por fonte, timestamp comprovado; notícias no briefing <=24h |

## 4. Frequência PROPOSTA (não ativada)

- **Horária/intradiária:** eventos/notícias de fontes autorizadas, tempo severo e alertas logísticos quando houver infraestrutura contínua; rate limit e monitoramento de fonte são mandatórios.
- **Diária:** câmbio e cotações licenciadas, pluviometria e portos aprovados; programado ≠ realizado. Sem horário de fechamento, sinalizar SOURCE_LAG.
- **Semanal:** diesel ANP, progresso de plantio/colheita conforme publicação, export sales USDA.
- **Mensal:** CONAB, MDIC, ANTAQ, ANP industriais, ABIOVE e transporte por base; data de competência não equivale a data da publicação.
- **Trimestral/quadrimestral/anual:** Sindirações, IBGE pecuária, cana CONAB, PAM e cenários estruturais, conforme frequência real de cada provedor.

A cadência do catálogo é uma **proposta de inspeção da fonte**, não promessa de que novos dados existam a cada execução. Em período sem atualização deve-se registrar `NO_CHANGE` ou `SOURCE_LAG`, não republicar o mês antigo como novo.

## 5. Gates de promoção obrigatórios

1. **SOURCE_DISCOVERED:** página, responsável e granularidade demonstrados.
2. **ACCESS_VERIFIED:** API/URL oficial e direito de consulta/coleta/armazenamento confirmado por modalidade; segredo em vault quando aplicável.
3. **PARSER_TESTED:** exemplo real autorizado + fixture sintética, nulos/campos/encoding/unidades, teste contra mudança de layout.
4. **QUALITY_VALIDATED:** reconciliação com total primário, cobertura conhecida, ausência de duplicidade, quatro datas, perdas/exceções verificadas.
5. **PERSISTENCE_VALIDATED:** histórico incremental com edição e consulta as-of, backups e restauração testados.
6. **OPERATIONAL_READY:** ao menos três execuções em datas distintas quando a fonte mudar diariamente, observabilidade, retries com limites, freshness, alertas de quebra, sem custos não aprovados.
7. **PUBLICATION_ALLOWED:** política específica de uso, citação, derivação comercial e redistribuição; *não* presume licença pela abertura da página.

Um coletor só é operacional quando os sete gates se aplicam **à sua própria finalidade**. NENHUM indicador é automaticamente publicado pelo fato de o catálogo possuir sua fonte. Métricas com dados faltantes exibem `FONTE_INDISPONIVEL`, não zero.

## 6. Dependências prioritárias para o primeiro painel e briefing NIVON

**P0 (22 datasets):** séries CONAB de soja/milho e balanços; SIPEAGRO ração; Sindirações macroingredientes e ABIOVE esmagamento; MDF-e MT, ferrovia e ANTAQ; MDIC NCM e município/SH4; diesel ANP revenda/refinaria/importação; PTAX; açúcar/algodão/boi quando dados primários disponíveis; portos Santos, Paranaguá e São Francisco do Sul.

As janelas de **24 horas** aplicam-se exclusivamente às notícias do briefing. Cotações exibem hora/data do fechamento disponível, sem fingir que são notícias novas. O NIVON produz e edita o briefing, usando uma **interface de envio** ao WhatsApp AI somente quando essa integração estiver autorizada. WhatsApp AI mantém coleta e relatório de fretes sob seus próprios contratos, sem virar fonte de toda a inteligência do NIVON.

## 7. Comandos locais, 100% sem rede

```bash
PYTHONPATH=src python -m nivon.catalogo_fontes --resumo
PYTHONPATH=src python -m nivon.catalogo_fontes --produto DIESEL --prioridade P0
PYTHONPATH=src python -m nivon.cobertura
PYTHONPATH=src python -m nivon.orquestrador_fontes --prioridade P0 --resumo
PYTHONPATH=src python -m unittest discover -s tests -v
```

No Windows PowerShell: primeiro `$env:PYTHONPATH="src"` e executar `python -m nivon.catalogo_fontes --resumo`.

**Fonte central do código:** [NIVON no GitHub](https://github.com/brunocapellari-dotcom/NIVON). Nenhum deploy, merge, pagamento ou liberação de conexão restrita é autorizado pelo presente documento.
