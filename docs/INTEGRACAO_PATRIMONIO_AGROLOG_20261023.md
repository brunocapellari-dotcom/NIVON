# Migração operacional de patrimônio AgroLog MT → NIVON (23/10/2026)

## Escopo deste lote — executado em branch empilhada sobre PR #137

* Registro histórico de 68 fontes do arquivo `AgroLogMT/collector/config/data_source_registry.v1.json`, fixado ao commit `2d28a3226b4e59db4bc758c26965ec8acb29c61e`. Armazenado em `config/legado_agrolog/registro_coletores.v1.json`.
* Catálogo de **680 URLs únicas** extraídas das abas **Dados, Radar e Conhecimento** da planilha AgroLog consolidada em Google Drive; 264 links classificados como dados, 87 como radar e 332 como conhecimento (o mesmo link pode ter mais de uma classe). Armazenado em `config/legado_agrolog/catalogo_links.v1.json`.
* Ferramenta `src/nivon/legado_agrolog.py` que reconcilia provedores do AgroLog com o catálogo do NIVON sem tocar em endpoints externos. **A correspondência é apenas por provedor, não constitui homologação do dataset.**
* Testes de regressão: `tests/test_legado_agrolog.py`.

### Execução local (sem rede, sem banco)

```bash
PYTHONPATH=src python -m nivon.legado_agrolog --resumo
PYTHONPATH=src python -m nivon.legado_agrolog --saida /tmp/conciliacao_agrolog_nivon.json
PYTHONPATH=src python -m unittest discover -s tests -p test_legado_agrolog.py -v
```

A ferramenta entrega: número de fontes, correspondência do provedor, datasets do NIVON relacionados, fonte sem correspondência, referência do código legado, próxima ação, status histórico original e prioridade sugerida. Esses resultados **não** são declarações de fontes novas em produção.

## Política de segurança e integridade

1. `active` do AgroLog é **um status histórico** e não habilita coleta no NIVON. `enabled=false` e `scheduled=false` são imutáveis para esses snapshots de referência.
2. Não herdar licença, direitos de armazenamento, uso comercial ou redistribuição dos portais originais. Obter direitos por fonte/operação.
3. Endpoints de fontes não públicas não são copiados. Os nomes/caminhos de código são apenas referências rastreáveis.
4. URLs da planilha **não são baixadas**, seguidas, examinadas ou executadas automaticamente. Links HTTP legados continuam apenas no inventário, nunca como fonte autorizada.
5. Correspondência genérica de provedores não significa equivalência de datasets nem autoriza sumarização de valores sem tipos, unidades, competência e safra.
6. Evidências de coleta, snapshot RAW, hash, disponibilidade histórica verificada, qualidade, persistência e atualização continuam obrigatórias antes da promoção.
7. Preservar o catálogo NIVON canônico; este lote não o modifica e não aciona scheduler, Cloud, Neon, credenciais, custos ou provedores.

## Próximas integrações de maior valor

| Prioridade | Frente | Componentes AgroLog | Critério de conclusão |
| --- | --- | --- | --- |
| P0 | CONAB Safra e Armazéns | `conab_safra_pipeline.py`, `conab_armazens_pipeline.py`, backfill/contratos | RAW oficial, parsing, revisão histórica, persistência e backtest temporal |
| P0 | IMEA | `imea_operational_pipeline.py`, `imea_operational_xlsx.py`, data marts | Atualização via fonte autorizada, preços, fretes, progresso, comercialização; direitos e storage separados |
| P0 | ANTT/ANTAQ | registro de fontes e contratos, SIADE/MDF-e, hidrovias | TU/TKU e recortes compatíveis; amostra MDF-e jamais total |
| P0 | Portos/CDP/AIS | `official_lineup_html.py`, `official_lineup_pdf.py`, parsers por porto | Programação versus realizado, DUV/escala, geocerca e divergência CDP validados |
| P1 | CONAB/Comex/USDA/Argentina | `zero_cost_public_sources.py`, backfills e WASDE vintages | Captura real, timestamp de disponibilidade e versões recuperáveis |
| P1 | Radar analítico | 87 links históricos de Radar e abas Execucoes/Itens/Lacunas | Alimentação contínua, janela móvel do briefing 24 h e monitor de publicações atrasadas |
| P1 | Biblioteca técnica | 332 links classificados Conhecimento | Ingestão documental autorizada, provenance e revisão técnica |

### Dependências reais

- A branch deste PR parte do SHA do PR #137, que por sua vez depende das PRs #134 e #120; não mesclar diretamente com `main` sem integração das bases.
- A coleta recorrente completa e o BigQuery em produção ainda não estão comprovados pelo inventário. Requerem verificação de infraestrutura, permissões, quotas e custos.
- Priorizar integração E2E por lote sobre testes unitários isolados: coletor autorizado → RAW → parser → armazenamento → QC → motor → relatório → execução agendada.

## Regra de continuidade

Usar o relatório gerado por `nivon.legado_agrolog` como uma fila de reconciliação, não como a fonte de verdade operacional. Antes de portar qualquer coletor, comparar hashes/linhas/contratos com o código já presente nas branches do NIVON e reutilizar uma implementação existente quando ela for equivalente ou superior.


## Segundo lote — parser e persistência IMEA operacional (implementado na PR #147)

A migração deixou de ser somente documental. Componentes portados/adaptados do AgroLog:

- `src/nivon/xlsx_legado.py`: leitura XLSX protegida contra arquivo ZIP exagerado, DTD/entidades XML, path traversal e planilhas fora de dimensão; não avalia fórmulas. Baseado no `collector/xlsx_reader.py` AgroLog. Dependência `defusedxml` substituída por verificação explícita de DTD/ENTITY e limites.
- `src/nivon/imea_operacional_xlsx.py`: interpretação das **cinco abas** `indicadores diarios`, `indicadores semanais`, `frete`, `semeadura`, `colheita`, mantida a proveniência `collector/imea_operational_xlsx.py` e QA de chave natural.
- `src/nivon/imea_legado_pipeline.py`: adapter que transforma dados de planilha em observações versionadas, usa o módulo NIVON preexistente `ingestao_fontes_reais.gravar_lote` e mantém lote **somente em `IMEA_WORKBOOK_LEGADO_STAGING` no estado `QUARANTINED`**.
- `src/nivon/ingestao_fontes_reais.py`: aceita MIME XLSX real para persistência local versionada.
- `tests/test_imea_legado_pipeline.py`: ensaio integrado de ZIP/XML -> cinco abas -> 19 observações sintéticas -> RAW SHA-256 -> SQLite -> replay idempotente -> revisão de preço -> exportação JSONL -> plano de BigQuery `executado=False`. Inclui casos de entrada perigosa, dados inválidos e autorização por operação.

Proveniência preservada: URL do workbook original, hash do conteúdo e de cada observação, referencia, competencia, publicacao (se comprovada externamente), coleta com timezone; diferenciam-se `INFORMADO` e `ESTIMADO`. Frete publicado não é frete contratado. A revisão de preço entra como nova versão distinta, sem apagar o vintage anterior.

### Limites deliberados

1. **Não ler mais dados do Drive como única verdade.** O arquivo histórico servirá como backfill e conciliação após a confirmação de publicações contemporâneas. A obtenção incremental diretamente do IMEA ainda não foi integrada aqui.
2. A base local e o JSONL não são BigQuery em operação. A configuração de destino do `IMEA_WORKBOOK_LEGADO_STAGING` não constitui permissão para publicar/consultar em marts.
3. O mapeamento de indicadores IMEA é conservador: produção/safra pode sugerir `IMEA_MT_SAFRA` mas valores de preços, CBOT e frete não serão forçados para `IMEA_FISICO`; o contrato canônico de frete ainda requer cadastro e validação.
4. Para chamar `persistir_lote_local(...,tipo="REAL_AUTORIZADO")`, o código exige explicitamente `COLETA`, `ARMAZENAMENTO`, `USO_INTERNO` e uma evidência textual; isso NÃO é verificação independente de direito comercial ou divulgação.
5. CLI aceita somente validação sem persistir ou fixture `--sintetico`. **Nunca indicar --sintetico para registrar dado real como sintético**.
6. Os exemplos de testes são sintéticos: não demonstram que um workbook real de 2026 tem esse layout.

Comandos E2E sem rede:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_imea_legado_pipeline.py -v
# Exemplo de validacao de workbook local sem gravacao:
PYTHONPATH=src python -m nivon.imea_legado_pipeline /caminho/autorizado/arquivo.xlsx \\
  --origem https://drive.google.com/file/d/FILE_ID_REAL \\
  --coletado-em 2026-10-23T10:00:00-04:00
```

### Próximos gates

- CONAB: o NIVON já tem parsers próprios para XLS/XLSX e SICARM, incluindo snapshot ledger; comparar com contratos AgroLog, complementar temporalidade as-of sem duplicar pipeline.
- IMEA: identificar feed/publicações correntes, capturar original de modo autorizado, testar parser em amostra real sem dados pessoais, registrar dataset canônico de frete e mapear os cinco grupos; só então agendar ingestão e integrar com motor de preços/fretes.
- Nuvem: validar ADC, IAM, dataset, zero-cost, políticas de retenção e restore antes da persistência final BigQuery.


## Terceiro lote — CONAB as-of com prova de disponibilidade histórica

* `src/nivon/conab_vintage_asof.py`: sidecar `conab_disponibilidade_historica` junto ao **store CONAB já existente**, sem substituir `conab_store.py`. Exige documento oficial, hash do documento, data da publicação original, data da disponibilidade, registro da auditoria e aprovação explícita antes de aceitar um cutoff anterior à coleta. **URL e hash isolados não constituem prova: o status inicial é PENDENTE_AUDITORIA e não desbloqueia histórico**.
* `tests/test_conab_vintage_asof.py`: casos de corte anterior/posterior à coleta, documento pendente, homologação expressa, revogação, fonte não oficial, datas inconsistentes, revisões conflitantes e publicação ausente.
* Mantém `data_coleta` real, sem inventar momento histórico de coleta; para vintages distintos com mesma publicação, o retorno é `AMBIGUO_VINTAGE_MESMA_PUBLICACAO`, não um dado adivinhado.
* Esta consulta específica não substitui consultas canônicas existentes, nem implica que qualquer documento CONAB já esteja homologado. Auditoria documental sobre versões reais continua pendente.

Teste integrado offline:
```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_conab_vintage_asof.py -v
```

