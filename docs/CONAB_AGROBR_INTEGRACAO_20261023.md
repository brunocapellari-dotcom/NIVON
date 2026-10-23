# NIVON — Integração CONAB pelo AgroBR 2.0 (23/10/2026)

## Decisão de arquitetura

O AgroBR já possui conectores CONAB de safras por levantamento, série histórica, balanço oferta/demanda e progresso semanal. O pacote já está fixado no extra opcional `NIVON[agro]` como `agrobr==2.0.0`. Reutilizaremos a API pública `agrobr.conab.safras`, em vez de criar um novo parser dos boletins para a rota normal. O coletor pontual RAW existente permanece útil para auditoria de bytes/cadeia de custódia, como segunda verificação, não deve disputar a ingestão estruturada.

Referência oficial da biblioteca: https://agrobr.dev/docs/api/conab/ e https://agrobr.dev/docs/contracts/serie_historica_safra/ . A biblioteca é MIT; os dados CONAB continuam sujeitos às condições específicas da fonte. Ao usar `agrobr.conab` diretamente, não acionar `datasets.estimativa_safra`, cujo fallback IBGE/LSPA modifica silenciosamente o conceito de fonte.

## Prioridades de execução e testes

| Prioridade | Entrega | Teste verificável | Estado |
|---|---|---|---|
| P0 | Consultar por cultura, safra, UF e levantamento EXPLÍCITO | Async mock do contrato público `conab.safras(...,return_meta=True)` | Implementado |
| P0 | Distinguir MILHO total e 1ª/2ª/3ª safras | Testes de produto e chaves específicas; não somar sem fórmula auditada | Implementado |
| P0 | Normalizar sem mudar unidade original | Mantém mil ha, kg/ha, mil t; `area_colhida` CONAB nula | Implementado |
| P0 | Impedir substituição por série histórica mais nova ou edição errada | Confronto `source_details.publicacao` com safra/levantamento explícitos | Implementado |
| P1 | Processar soja e milho em um lote e gravar SQLite staging sem liberar previsão | Consulta seriada e tabela `conab_agrobr_staging`, idempotente | Implementado |
| P1 | Exercitar AgroBR instalado e fonte HTTP real | Execução pontual em worker Linux com `pip install -e '.[agro]'` e conectividade HTTPS | **Pendente** |
| P1 | Aprovar comportamento da API com XLSX real e identificar revisões mensais | Confrontar metadados, valores e unidades com arquivos oficiais específicos | Pendente |
| P2 | Disponibilizar vintages e análises/retrotestes | Provas independentes de publicação e disponibilidade, jurídico/licença, qualidade | Bloqueado |

## Um comando, após instalação do extra

```bash
python -m pip install -e '.[agro]'
PYTHONPATH=src python -m nivon.conab_agrobr_safras \
  --safra 2024/25 --levantamento 5 --uf MT \
  --produtos soja,milho,milho_1,milho_2,milho_3 \
  --permitir-consulta --out conab_agrobr_staging.json \
  --sqlite conab_agrobr_staging.sqlite
```

**Apenas comando de execução futura:** nenhum download via AgroBR 2.0 ocorreu nesta sessão do ChatGPT. A tentativa de acessar PyPI no executor local falhou por indisponibilidade de rede, e o pacote não estava instalado; portanto, os testes aprovados são determinísticos com API mock. A consulta em uma infraestrutura com rede também pode falhar por indisponibilidade do portal e deve falhar fechado, não retornar números presumidos.

Requer aprovação operacional e direitos confirmados para executar a consulta, internet e saída inédita. O CLI recusa a chamada sem a flag explícita `--permitir-consulta`, exige levantamento 1..12 e confere `MetaInfo.source_details['publicacao']`. Cada linha retém identificador de produto, UF, safra, levantamento, data publicada conforme AgroBR, origem CONAB e versão do parser. Campos de área usam MIL_HA, produtividade KG_HA, produção MIL_T, sem tratar área plantada como área colhida.

Os dados vão a uma tabela separada `conab_agrobr_staging`, com classe SEM_RAW_SEM_VINTAGE. Não são inseridos em histórico de revisões, previsões ou banco canônico. O hash do JSON normalizado não é hash da planilha oficial. Em particular, mesmo consulta a `levantamento=5` feita hoje não autentica por si só que esses bytes e indicadores estavam disponíveis na data histórica; o ponto no tempo requer arquivo versionado, datas e proveniência independentes.

## APIs do AgroBR aproveitáveis depois desta prioridade

- `conab.serie_historica(produto, ano_inicio=..., ano_fim=..., uf=..., return_meta=True)`: base consolidada, não substitui vintages mensais. Produtos `milho_1`,`milho_2`,`milho_3` definidos no contrato v1.1.
- `conab.balanco(produto, safra=..., levantamento=..., return_meta=True)`: oferta e demanda, com edição específica e convenções próprias de estoque/consumo.
- `conab.progresso_safra(...)`: o projeto já possui `conab_agrobr.py` com adaptador e portão de direitos; não recriar este conector.
- `conab.levantamentos()`: lista catálogo da fonte; usar somente para descoberta controlada, com metadados de edição e freshness, sem associar data de consulta a publicação.

## Evidência e próximos bloqueios

Arquivo implementado: `src/nivon/conab_agrobr_safras.py`. Testes: `tests/test_conab_agrobr_safras.py` com casos de safra explícita, URL institucional, unidade, nulidade, metadados, mudança de edição, granularidade de milho, consulta assíncrona e SQLite staging. Fronts SOJA/MILHO recebem entrypoint na allowlist de `registro_motores.py`, com `operational_enabled=false`, `scheduled_enabled=false`, `inputs_reais_homologados=false`, `previsao_homologada=false`.

Próximo P0 real: executar a consulta em infraestrutura autorizada com AgroBR 2.0 instalado e coletar a edição vigente específica; comparar com o RAW oficial do levantamento, validar cultura/UF/unidades/valores e somente então promover a ingestão canônica sob critérios de direitos, temporalidade e qualidade. Não houve cron, deploy, gastos ou merge na main.
