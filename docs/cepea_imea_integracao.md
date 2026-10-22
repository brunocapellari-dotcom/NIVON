# NIVON — CEPEA e IMEA: acesso, widgets e ingestão analítica

Estado em 21/10/2026. **Nenhuma cotação real CEPEA/IMEA foi gravada no PostgreSQL do NIVON nesta etapa.** A PTAX BCB possui integração independente, já funcional. Os 42 widgets são referências de exibição e NÃO fornecem licença nem endpoint estruturado garantido para captura sistemática.

## Política de fontes

- **CEPEA/ESALQ:** documentação de licenças do agrobr classifica indicadores e séries sob **CC BY-NC 4.0**, observadas atribuição, indicação de alterações e uso não comercial. Confirmar escopo do indicador e eventuais restrições do método de acesso no sítio oficial; usar fontes sem contornar proteções técnicas. **Consulta manual de diagnóstico permitida explicitamente no módulo, gravação automática NÃO habilitada.**
- **IMEA:** Termo de Uso em https://imea.com.br/imea-site/termo-de-uso.html, seção Direitos Autorais, reserva IP das bases, dá licença limitada e proíbe uso não autorizado inclusive não comercial; arquivos **não públicos** não podem ser compartilhados sem autorização escrita. O acesso às séries públicas é documentado como \`zona_cinza\` no agrobr. **Não habilitar coleta sistemática nem armazenamento histórico de IMEA sem decisão documentada sobre o recorte.**
- **Notícias Agrícolas:** widgets para mostrar cotações no painel; conteúdo de origem CEPEA sob CC BY-NC mantém licença de origem; fallback NA do agrobr classificado \`zona_cinza\` e jamais aceito silenciosamente como \`cepea\`.

Referências: https://agrobr.dev/docs/api/cepea/, https://github.com/bruno-portfolio/agrobr/blob/main/docs/sources/imea.md, https://agrobr.dev/docs/licenses/, https://imea.com.br/imea-site/termo-de-uso.html.

## Conectores e teste atual

O módulo \`nivon/fontes_agrobr.py\` implementa:
- Gate explícito de finalidade NC para CEPEA e bloqueio IMEA sem documentação;
- \`validar_cepea\`: valida preço positivo e finito, data e unidade, registra competência, origem e \`data_coleta\`; rejeita automaticamente entradas do Notícias Agrícolas e anomalias;
- \`inspecionar_imea\`: inspeção offline de tipo de indicador, deduplicação, classificação de zeros, separação de semente e grão; mantém \`data_referencia = null\` se fonte fornecer apenas data de publicação;
- \`consultar_cepea_para_validacao\`: única consulta manual do agrobr (\`await cepea.indicador(...,return_meta=True)\`) sem DB write. Relata apenas contagens; fallback Notícias Agrícolas inteiro é bloqueado quando indicado no MetaInfo.

Teste unitário: \`python -m unittest tests/test_fontes_agrobr.py -v\` (fixtures sintéticos).
Smoke real manual/CI: \`.github/workflows/cepea-diagnostico.yml\`, consulta apenas soja CEPEA, 01–20/10/2026, com risco de bloqueio externo; sucesso depende de registros CEPEA originais e **não significa autorização para reuso automático de todas as séries**.

## Evidência real de diagnóstico CEPEA — 21/10/2026

Execução da GitHub Action [CEPEA diagnóstico #39652833890](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39652833890): o agrobr foi instalado corretamente e a chamada da série **soja** para 01–20/10/2026 foi efetivamente executada. Houve aviso de fallback para Notícias Agrícolas; a rotina NIVON reconheceu `MetaInfo.data_sources` e lançou `DadosNaoHomologados`. **Nenhuma observação CEPEA foi homologada ou gravada no banco**.

Isso não prova que CEPEA está indisponível em todos os ambientes, apenas que o canal direto não funcionou nessa execução. O workflow de diagnóstico foi atualizado para retornar estado explícito `PRIMARIA_INDISPONIVEL_FALLBACK_BLOQUEADO`, separado de sucesso de coleta. É proibido contornar controle de acesso ou reclassificar números NA como origem CEPEA.

## Produto a produto (ordem)

| Fonte | Dados prioritários | Razão |
|---|---|---|
| CEPEA | Soja Paranaguá / Paraná (widgets 121, 26), milho ESALQ/B3 (91) | Referências nacionais físicas para motor de tendência |
| CEPEA | Boi ESALQ/B3 (128), café Arábica (28), algodão (84) | Preços de outras cadeias |
| CEPEA | Açúcar cristal (36) e etanol quando homologado | Cadeia sucroenergética |
| IMEA | Soja disponível (199), milho disponível (198) por praça de MT | Formação de preço e basis local |
| IMEA | Algodão (131), boi à vista (122), frete de grãos | Integração logística/comercialização |

IDs de widgets **não** devem virar IDs de séries primárias. No IMEA, preservar \`indicador_id\` original de texto (pode ter 18 dígitos) e distinguir granularidade regional.

## Modelo de banco a homologar antes de guardar dados reais

Campos mandatórios: \`source\`, \`source_series_id\`, \`product\`, \`location\`, \`quote_type\` (físico/futuro/premio), \`unit\`, \`value\`, \`reference_date\` (NÃO confundir com divulgação), \`published_at\` (nullable), \`collected_at\`, \`competencia\`, \`license\`, \`epistemic_type\`, \`retrieval_channel\`, \`parser_version\`, \`quality_status\`, \`revision_id\`, \`source_url\`; zero desconhecido ou sem preço vai para quarentena.

Preço de soja R$/sc60kg de Sorriso, indicador CEPEA Paranaguá R$/sc60kg e Chicago US¢/bu não são séries intercambiáveis. Identidade inclui praça, unidade, modalidade, safra (se relevante), publicação, vencimento (futuro) e identificador original.

## Sequência operacional para homologação

1. Consulta CEPEA limitada e sem armazenamento, validando que \`fonte=cepea\`, dados não stale e unidade/praça corretas;
2. Confirmar licença aplicável, fonte primária e direitos de armazenamento no NIVON não comercial; documentar a decisão por produto/finalidade;
3. Implementar ingestão incremental no banco isolado com restrições de leitura, revisões, backfill controlado e auditoria;
4. IMEA: obter confirmação das condições aplicáveis à coleta das séries públicas e do armazenamento particular; esclarecer \`data_publicacao\` versus \`data_referencia\`, zeros e duplicatas;
5. Usar apenas séries liberadas e testadas em tendências; marcar \`SOURCE_LAG\`, ausência e revisões.

NÃO ativar scraping dos widgets, bypass de controles de acesso, publicação de CSV de terceiros no GitHub ou fontes automáticas IMEA com direitos ainda incertos.
