# NIVON — Fonte Notícias Agrícolas: catálogo e ingestão segura

## Estado em 21/10/2026

- **42 IDs de widgets** catalogados a partir de imagens fornecidas pelo usuário, em sete grupos: algodão (6), bovinos (10), café (4), financeiro (3), milho (5), soja (10), sucroenergético (4).
- O widget oferece incorporação JavaScript para visualização; **isso não comprova licença para coleta, histórico ou redistribuição**.
- Não foi habilitado coletor remoto, agendamento, execução em produção nem persistência de preços reais.
- Os IDs não são endpoints de API homologados e não equivalem a contratos de dados.
- Priorizar API/histórico oficial CEPEA, IMEA, B3, CME/ICE, BCB quando tecnicamente acessível e autorizado.

## Código

`python -m nivon.cotacoes validar-catalogo` verifica 42 IDs únicos, grupos e permissões.

`python -m nivon.cotacoes url-widget 199` constrói endereço **apenas para incorporação visual** (não coleta).

`python -m unittest discover -s tests -v` executa testes sintéticos sem acesso externo.

A importação de arquivo JSON sintético é possível com `python -m nivon.cotacoes importar --arquivo exemplos/cotacoes_sinteticas.json --banco /tmp/nivon_cotacoes.sqlite3 --sintetico`.

## Contrato de observação

Cada registro de entrada precisa conter: `id_widget`, `instrumento`, `praca` (string ou null), `vencimento` (string ou null), `valor` (decimal em texto), `unidade`, `data_referencia` (AAAA-MM-DD), `data_publicacao` e `data_coleta` (ISO 8601 com fuso), `competencia` (AAAA-MM), `classificacao`, `fonte_original`.

A base SQLite mantém o valor original em decimal textual e grava um hash por registro. Reimportações idênticas são ignoradas; correções de valor são mantidas como nova versão na mesma chave de série. Não converte/mescla automaticamente praças, unidades ou vencimentos. Classificações: OBSERVADO, INFORMADO, ESTIMADO, INFERIDO, PROJETADO, SINTETICO. Dados de terceiros recebidos de um intermediário devem ser rotulados conforme a evidência — normalmente INFORMADO, e não OBSERVADO automaticamente.

## Gate de permissão

Para dados **reais**, importação exige arquivo de autorização local, não versionado, com `fonte: "Noticias Agricolas"`, `coleta_autorizada: true`, `armazenamento_autorizado: true`, `identificador_autorizacao` não vazio e `responsavel_validacao` não vazio. O preenchimento do arquivo **não substitui a verificação jurídica/documental**. Não colocar chaves, contratos e séries reais no repositório público.

## Próxima etapa técnica

1. Validar por escrito a origem, licença, operação permitida e atualização de cada provedor; registrar granularidade/unidades e referências históricas.
2. Implementar adaptadores das **fontes primárias autorizadas** em cima do contrato, sem raspagem presumida de widgets.
3. Rodar piloto ponta a ponta para soja/IMEA/CEPEA/PTAX; testar agendamento, falhas, revisões, dados defasados e integrações com motor de tendências.
4. Habilitar armazenamento e automação de produção somente depois dos testes e revisão de acessos/custos.

## Integração verificável 23/10/2026 — fonte primária → widget → Neon

Foi adicionada e **executada** no Neon `database/neon_widgets_origens_verificadas.sql`, que cria a visão somente de leitura `public.nivon_widgets_origens_verificadas_v`. Ela referencia diretamente as tabelas existentes CEPEA e BCB/PTAX e não raspa nem acessa o JavaScript dos widgets. O vínculo inicial é **#26 soja Paraná, #121 soja Paranaguá, #232 câmbio PTAX USD/EUR**. O esquema também prepara o vínculo de **#91 milho CEPEA**, mas sem registros coletados até a verificação.

Teste SQL após implantação: **9.304 observações vinculadas a 3 IDs** (30 CEPEA, 9.274 pontos PTAX em lados COMPRA/VENDA), sem coletas diretas de widget. Cada registro conserva valor e unidade originais, referência, natureza `INFORMADO`, licença e o NULL de publicação quando não fornecida. Volume de registros vinculados **não** é volume de consultas ao widget.

### Ponte preparada para a estrutura BigQuery

O exportador `nivon/widgets_exportacao.py` converte um snapshot **privado** dessa visão em JSONL compatível com o contrato da tabela `nivon_core.observacoes` previsto na PR #84. Não lê Neon diretamente, não conecta ao BigQuery, não executa carga nem cria recurso GCP. O valor de `origem_sha256` no arquivo exportado representa SHA-256 da **linha normalizada da visão Neon** (não os bytes RAW publicados pelo provedor); essa distinção aparece em `atributos.hash_tipo` e `atributos.hash_raw_fonte_primaria_disponivel=false`. A carga de `raw_manifest` exige origem RAW comprovada separadamente.

Para preparar snapshot fora do repositório público (exemplo **não executado**):

```sql
-- No psql com acesso autorizado, sempre para diretório privado:
\copy (SELECT row_to_json(v) FROM public.nivon_widgets_origens_verificadas_v v WHERE data_referencia >= DATE '2026-01-01') TO '/diretorio-privado/widgets_neon.jsonl'
```

```sh
python -m nivon.widgets_exportacao --entrada /diretorio-privado/widgets_neon.jsonl --saida /diretorio-privado/widgets_bigquery.jsonl
```

O arquivo de saída é criado como privado (0600) e é removido se qualquer linha falhar no contrato. Há bloqueio de widget desconhecido, mapeamento de origem incorreto, data sem fuso, coleta de widget não autorizada, linha duplicada e publicação posterior à coleta. O relatório informa cobertura, contagem e hash sem imprimir preços.

**Bloqueios restantes:** a PR #84 não homologou credenciais, billing, IAM, dataset ou automação do projeto `nivon-data`; o conector BigQuery não está disponível. Não declarar o BigQuery carregado, nem promover os 39 demais IDs com base no catálogo. IMEA segue com data de referência da cotação não comprovada e staging vazio. A integração operacional só poderá ser declarada após carga autenticada, reconciliação por data/vintage e pelo menos duas execuções incrementais distintas.
