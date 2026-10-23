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
