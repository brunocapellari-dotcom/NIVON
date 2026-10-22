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
