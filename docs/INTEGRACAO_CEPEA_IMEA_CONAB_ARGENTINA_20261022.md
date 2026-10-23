# NIVON — integrações CEPEA, IMEA, CONAB e Argentina
**Data de corte:** 22/10/2026. **Uso:** interno não comercial. **Estado:** protótipo offline; coleta contínua e nuvem NÃO homologadas.

## Matriz de fontes e transportes

| Fonte | Séries | Transporte priorizado | Estado |
|---|---|---|---|
| CEPEA | preços soja, milho, boi, açúcar, etanol, algodão | API/exportação autorizada + importador da PR #119 | API e limites de automatização não homologados |
| IMEA | cotações locais MT, fretes, avanço da safra, comercialização, custos | exportação/API autorizada + importador da PR #119 | endpoint e termos de coleta em aberto |
| CONAB | histórico e revisão de safras, área, produção, rendimentos, oferta/demanda, plantio e colheita | XLSX/CSV oficial; reaproveitar componentes e PRs #16–#115 | parsing/captura supervisionada; execução cloud não comprovada |
| Argentina SAGyP | soja, milho, trigo, demais culturas por safra/província/departamento | catálogo oficial CKAN, CSV validado, adaptador local deste PR | parser e testes offline; GET real e licença de download por endpoint pendentes |
| Argentina SIO Granos | preço, compras e vendas registradas por zona e data | exportações oficiais documentadas, se permitidas | descoberta, sem parser homologado |
| Argentina DJVE / Monitor Comercial | exportações declaradas, compras por indústria e exportador | exportações oficiais documentadas, se permitidas | descoberta, sem parser homologado |

Fontes:
- CEPEA [licença CC BY-NC para o conteúdo do site](https://cepea.org.br/br/licenca-de-uso-de-dados.aspx), [consulta de séries](https://cepea.org.br/br/consultas-ao-banco-de-dados-do-site.aspx); **licença do site não é contrato de API**.
- IMEA [indicadores](https://www.imea.com.br/imea-site/indicadores), [relatórios](https://www.imea.com.br/imea-site/relatorios-mercado) e [metodologia de comercialização de soja](https://imea.com.br/imea-site/view/uploads/metodologia/soja/SojaComercializacao.pdf). Comercialização é percentual **acumulado por safra**, não fluxo diário.
- CONAB [Portal de Informações](https://portaldeinformacoes.conab.gov.br/) e [safras gov.br](https://www.gov.br/conab/pt-br).
- Argentina [estimativas oficiais completas](https://datos.magyp.gob.ar/dataset/estimaciones-agricolas/archivo/95d066e6-8a0f-4a80-b59d-6f28f88eacd5), [soja](https://datos.magyp.gob.ar/dataset/soja-siembra-cosecha-produccion-rendimiento/archivo/ba694aa3-99d2-4d7d-9936-60f88e36ad9a), [milho](https://datos.magyp.gob.ar/dataset/maiz-siembra-cosecha-rendimiento-produccion/archivo/9a6a02f8-ef58-4250-87c2-f639fec502f1), [trigo](https://datos.magyp.gob.ar/dataset/trigo-siembra-cosecha-produccion-rendimiento/archivo/50f0edcc-4dfc-4afb-b78a-b164601d36ae), [dados abertos e SIO Granos](https://www.argentina.gob.ar/economia/agricultura/datos-abiertos), [Monitor Comercial](https://monitorssma.magyp.gob.ar/) e [DJVE](https://www.magyp.gob.ar/mercadosagropecuarios/DJVE.php).

## Implementação incluída no PR

O módulo `src/nivon/argentina_agricultura.py` oferece quatro UUIDs de recursos oficiais SAGyP, URL candidata `resource_show` CKAN, GET exclusivamente opt-in para **metadados**, parser de CSV (11 colunas oficiais) e importação autorizada para SQLite local. Preserva IDs argentinos com zeros, números decimais, hash SHA256 por edição, transação, idempotência e histórico por safra/departamento. **Nenhum recurso externo retornado pelo CKAN é baixado automaticamente.**

O storage local é **quarentena, não série de produção**: sem publicação/disponibilidade verificadas e sem passagem para relatórios ou backtesting. Guardar RAW privado/imutável separado. Nunca colocar arquivos de terceiros, dados autenticados ou tokens no GitHub.

Testar offline:
```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_argentina_agricultura.py -v
```
Esses testes usam fixtures sintéticas. Não comprovam acesso HTTP real.

## Arquitetura-alvo, não ativada

Fonte → autorização por operação → descoberta → GET autorizado com host/MIME/timeout/rate limit → RAW imutável com SHA e edição → parser → normalização territorial/temporal → validação → persistência versionada → BigQuery → motores/IVO.

Frequências **propostas**: CEPEA/IMEA após fechamento oficial em dias úteis; CONAB semanal (progresso) e mensal (estimativas); Argentina SIO/DJVE diária/semanal conforme publicação; SAGyP verificar semanalmente metadados e atualizar CSV quando houver mudança (frequência do catálogo semestral e revisões eventuais). Nunca apresentar valor antigo como atual.

**Gates antes de operação contínua:**
1. Direitos individualizados de consulta, coleta, armazenamento, processamento e redistribuição; atribuição e limites de taxa.
2. HTTP real de origem comprovada + contrato do CSV e mudanças de layout; redirecionamentos e hosts externos bloqueados até homologação.
3. Arquivo RAW e metadados de publicação/data de corte, competência, referência, coleta e disponibilização; revisão histórica como nova vintage.
4. Conciliação de unidades/campanhas com dados oficiais, anomalias e vazios; estatística provisional/estimativa separada de OBSERVADO.
5. E2E de parser → staging privado → query SQL → série canônica do NIVON → relatório; testes e execução em três edições.
6. Custos Google Cloud explicitamente aprovados, quotas e alarmes; nenhum deploy sem controle.

**Semânticas que não podem ser confundidas:** contratos SIO ≠ tonelagem fisicamente entregue; DJVE ≠ embarque realizado; percentuais IMEA de comercialização ≠ volumes sem base produtiva; preço CEPEA/IMEA ≠ equivalente em ARS sem praça, moeda, unidade e data; atualização de arquivo ≠ publicação oficial verificada.

## Pendências prioritárias

- Integrar e consolidar a PR #119 (CEPEA/IMEA supervisionados) e as PRs de CONAB na branch canônica; `main` ainda não contém todas as frentes.
- Validar CKAN real e URL de CSV argentino em executor autorizado; conferir CC BY 4.0 do recurso específico e condições efetivas, tamanho e período.
- Criar os adaptadores de arquivos SIO e DJVE depois de confirmar formatos e direitos — sem inventar endpoint privado.
- Criar job de execução + histórico Cloud Storage/BigQuery somente após confirmar a estrutura real do projeto Google Cloud.


## Avanços executados em 22/10 (continuação)

- `src/nivon/conab_indice_progresso.py`: leitura opt-in do **índice oficial semanal CONAB** (`www.gov.br/conab/.../progresso-de-safra`), extração de páginas candidatas a partir de HTML, allowlist de host e caminho, SHA da resposta e deduplicação. **Não baixa planilha.**
- `src/nivon/argentina_download_csv.py`: download controlado `GET` de CSV oficial identificado por metadados SAGyP, limitado a hosts públicos específicos, sem redirects, com gate de direitos, MIME, tamanho, proteção anti-HTML/WAF e SHA.
- `src/nivon/argentina_pipeline_local.py`: execução opt-in de `CKAN resource_show -> CSV -> RAW privado (0700/0600) -> SQLite de quarentena`, idempotente por hash, sem publicação no briefing e sem secrets.
- Foram acrescentadas suítes de testes sintéticos para índice CONAB, transporte CSV e pipeline integral local, sem dados externos reais.
- Evidência de CI: GitHub Actions `Testes locais NIVON`, execução #39889930077, commit `a949457adf1dc5e8f61a4259ffa8787e6bf307af`: **1406 testes, 5 ignorados, job validado com sucesso**.
- Em paralelo, o workflow `acessos-privados.yml` aparece como **falha no GitHub Actions sem jobs legíveis**. É um bloqueio de configuração/reconhecimento do workflow, não prova de falha de conexão SAGyP. Não se considera homologado.

### API real, RAW real e Google Cloud

Nesta sessão, `https://datos.magyp.gob.ar/api/3/action/resource_show?id=...` não pôde ser confirmado por requisição real no ambiente de trabalho. Logo, a coleta real ainda não ocorreu. O downloader aceita apenas domínio/arquivo oficial explicitamente validado e não ignora restrições de rede. O CSV sintético dos testes não é dado de mercado. O índice CONAB foi confirmado no portal, mas os novos módulos não fizeram GET real.

O pipeline usa exclusivamente SQLite + arquivo privado em ambiente local. **Ainda não está implantado nem agendado no Google Cloud, não foi validado BigQuery/GCS e não publica indicadores ao vivo.** Antes de cron, comprovar URL de download, licença de cada dataset, execução real com identificação de origem, retenção RAW no storage privado e mapeamento ao banco canônico. Não extrapolar direitos de CC BY 4.0 do dataset agrícola para SIO Granos ou DJVE.

Próximas tarefas:
1. Integrar índice de progresso CONAB aos parsers XLSX e storage revisionado já presentes nas PRs históricas, após teste de bytes reais.
2. Confirmar o CKAN real argentino e a URL dos CSV por recurso em executor autorizado; capturar e auditar ao menos uma edição.
3. Documentar schemas de SIO Granos e DJVE, especialmente diferença entre contratos/registro e embarque realizado.
4. Conciliar PRs #119/#122 e de CONAB antes de promover o código à base principal; validar `main` e Google Cloud existentes antes de qualquer deploy.

## Avanços adicionais — continuação da implementação

### CONAB: índice oficial -> páginas -> fila -> bytes -> normalização

Os módulos da branch agora são:
- `src/nivon/conab_sync_metadados.py`: CLI opt-in que lê **índice e páginas oficiais** (máximo de 10 páginas por chamada), sem downloads de anexos, e registra candidatos novos em SQLite.
- `src/nivon/conab_fila_publicacoes.py`: metadados versionados da semana e URLs candidatas de Plantio e Colheita, Fenologia e Monitoramento, com hash do HTML e filas idempotentes. Não infere a data de publicação.
- `src/nivon/auditoria_publicacao_conab.py`, `conab_replay_xlsx.py`, `captura_xlsx_conab.py`: reaproveitados das branches de dados CONAB, com prova de transporte para uma edição, validação de OOXML e RAW privado por pasta vazia; não há cron nem download ativo por padrão.
- `src/nivon/conab_ingestao_xlsx.py`: conecta um XLSX **já adquirido licitamente** e identificado na fila ao parser e ao armazenamento histórico `progresso_conab_historico.registrar_progresso_local`. A importação `REAL_AUTORIZADO` continua bloqueada pelo catálogo quando `enabled=false`.

Exemplo apenas após validar direito de consulta de metadados do portal:
```bash
PYTHONPATH=src python -m nivon.conab_sync_metadados \
  --banco /dados/privados/nivon_fontes.sqlite \
  --limite-paginas 3 --executar --direitos-consulta
```
O caminho local deve estar em volume privado durável. **Metadados não são planilhas baixadas.** Para captura XLSX de uma edição, usar o contrato `captura_xlsx_conab.py`, cuja interface exige os dados reais da página e do anexo e o diretório de destino privado e vazio. Não executar captura de XLSX com direitos desconhecidos.

### CEPEA e IMEA: coleta autorizada via biblioteca agrobr

- `src/nivon/cotacoes_agrobr_coletor.py`: `agrobr.cepea.indicador(produto,return_meta=True)` e `agrobr.imea.cotacoes(cadeia,return_meta=True)`, coletando apenas quando direitos individuais para consulta e armazenamento foram verificados e o operador ativa as flags.
- Estados em SQLite: `cotacao_lotes`, `cotacao_linhas`, `cotacao_lotes_coletas`; `QUARENTENA_SEM_HOMOLOGACAO_TEMPORAL`; dados nunca alimentam motor/briefing enquanto publicação e legalidade específicas não forem homologadas.
- Preservar indicador IMEA com ID de texto e praça/safra/unidade; não tratar `NaT`, `NaN` ou zero como publicação atual; duplicatas de valores distintos ficam documentadas, e origem `noticias_agricolas` não é atribuída automaticamente ao CEPEA primário.
- O CEPEA possui **API comercial oficial** com termos próprios no portal One-to-One: https://onetoone.cepea.org.br/termocontratacao-regulamentoapi/ . Não contratar neste projeto. A modalidade não comercial de indicadores públicos e a coleta por biblioteca de terceiros exigem respeito aos termos pertinentes.
- Documentação agrobr: https://github.com/bruno-portfolio/agrobr/blob/main/docs/api/cepea.md e https://github.com/bruno-portfolio/agrobr/blob/main/docs/api/imea.md .
- Status IMEA: o endpoint público usado pelo agrobr não equivale a licença escrita de extração/armazenamento ou redistribuição; direitos por operação ainda precisam ser verificados.

Exemplo técnico (NÃO executar até homologar direitos específicos):
```bash
pip install -e '.[agro]'
PYTHONPATH=src python -m nivon.cotacoes_agrobr_coletor \
  --fonte CEPEA --produto soja --banco /dados/privados/mercado.sqlite \
  --executar --direitos-consulta --direitos-armazenamento
PYTHONPATH=src python -m nivon.cotacoes_agrobr_coletor \
  --fonte IMEA --produto soja --banco /dados/privados/mercado.sqlite \
  --executar --direitos-consulta --direitos-armazenamento
```

### Argentina comercialização — contrato ainda não validado
- SIO Granos (https://www.siogranos.com.ar/) publica **documentação de API pública** em arquivo RAR, além de dados de operações informadas; o contrato de campos/endpoint não foi homologado neste ambiente. **Não inventar endpoint**.
- Monitor Comercial (https://monitorssma.magyp.gob.ar/) cobre compras do exportador/indústria, transportes e DJVE em painéis com cortes variáveis.
- Compras / DJVE (https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/areas/granos/_archivos/000058_Estad%C3%ADsticas/000020_Compras%20y%20DJVE%20de%20Granos.php?accion=imp): tabelas por safra, produto, comprador e volumes acumulados.
- Codificar normalizadores de comercialização **após verificar layout real de saída e licença**; registros informados de compra não são comprovantes de entrega e DJVE não é embarque efetivo.

### Homologação restante
Testes unitários/offline devem passar em PR. Ainda faltam execução HTTP real autorizada, bytes fonte verificados, aquisição incremental monitorada, API e licença SIO/DJVE, fila operando como scheduler, persistência em armazenamento cloud e integração ao banco/briefing NIVON. Não executar jobs de produção nem gerar custos enquanto essas dependências permanecerem.


## Atualização 22/10 — comercialização SIO e integração BigQuery

### Exportação SIO Granos (manual/autorizada, até 180 dias por consulta)

Fonte oficial: https://www.siogranos.com.ar/Consulta_publica/operaciones_informadas_exportar.aspx .
A página informa teto de 180 dias para a janela de declaração. Documentação de API pública: https://www.siogranos.com.ar/docs/DOC%20-%20API%20SIOGRANOS%20-%20Consulta%20Publica%20de%20Operaciones.rar .

- `src/nivon/argentina_sio_exportacoes.py` planeja janelas sem lacunas/sobreposição, importa exportações CSV após **verificação real do layout**, valida quantidade e moeda no locale argentino, aplica HMAC com chave privada ao ID de operação e versiona as edições em SQLite. Sem captura automática ASP.NET, scraping autenticado ou reutilização de credenciais.
- As colunas reais exportadas e a licença de armazenamento ainda **não foram homologadas**. A interface de mapeamento é explícita e fail-closed; nunca presumir que a tabela visual do site equivale ao CSV exportado.
- A agregação para outros motores é feita por edição/produto/província/data, mantendo `DECLARADO_NAO_ENTREGUE`. Exportações repetidas com operações sobrepostas não são somadas; vintages preservadas.

### Stage unificado e carga GCP

- `src/nivon/agro_bigquery_stage.py`: exportador OFFLINE em JSONL de tabelas SQLite locais de SAGyP, CEPEA, IMEA, CONAB e SIO. A camada SIO exporta SOMENTE agregados, nunca IDs/HMAC individuais.
- `sql/bigquery/002_agro_fontes_staging.sql`: DDL de landing em quarentena, separado das tabelas editoriais canônicas. Substituir variáveis de projeto/dataset depois de verificar GCP.
- `src/nivon/agro_bigquery_loader.py`: uploader BigQuery que, por padrão, apenas valida JSONL privado 0600/0700. Com execução real explicitamente autorizada, confirma tabela preexistente, esquema, localização, custo/armazenamento/licenças, usa job-id derivado de SHA e nunca cria recursos automaticamente. Não foi testado com credenciais reais.
- Dependência opcional em `pyproject.toml`: `pip install -e '.[gcp]'`. Em produção, ADC por workload identity/IAM de menor privilégio; nunca tokens em arquivo ou GitHub.

### Exemplos offline e preflight (não realizam cobrança)

```bash
# Stage de um SQLite local que contenha as tabelas previamente importadas
PYTHONPATH=src python -m nivon.agro_bigquery_stage \
  --banco /dados/privados/nivon_ingestao.sqlite \
  --saida /dados/privados/agro_stage.jsonl

# Inspecao de schema/valores LOCAL, sem conexao GCP
PYTHONPATH=src python -m nivon.agro_bigquery_loader \
  --arquivo /dados/privados/agro_stage.jsonl \
  --projeto PROJECT_ID_VALIDADO --dataset DATASET_ID_VALIDADO
```

O comando real de carga acrescentaria `--executar --custos-autorizados --armazenamento-autorizado --licencas-conferidas`, após configurações/IAM/licenças comprovados. **Não executar** enquanto essas verificações estiverem pendentes. A saída de staging e o SQLite devem ficar em volume privado e persistente, não no repositório.

Limitações que continuam abertas:
1. A rota exata de CSV SAGyP obtida do CKAN ainda não passou por download verificado no ambiente conectado.
2. A exportação SIO exige homologação por arquivo real + prova de condições de uso; sua documentação RAR não pôde ser inspecionada pelo leitor HTML.
3. A página de compras/DJVE do MAGyP tem dados públicos, mas layout para parser canônico ainda não validado: https://www.magyp.gob.ar/sitio/areas/ss_mercados_agropecuarios/areas/granos/_archivos/000058_Estad%C3%ADsticas/000020_Compras%20y%20DJVE%20de%20Granos.php .
4. O staging não substitui RAW imutável em GCS; não há GCS, Cloud Scheduler, Cloud Run, BigQuery real ou monitor de freshness ativados.
5. São necessárias validação da origem/datas e separação entre estimativas, registros de comércio, DJVE e embarques concluídos.


## Rodada 23/10 — execução multibanco + correção SIO + MERGE seguro

### SIO — corrigida a dimensão temporal

O limite de 180 dias do filtro na página pública é aplicado à **Fecha Declaración en SioGranos**, não à data de concertação.
- `argentina_sio_exportacoes.py` preserva agora `data_declaracao` (opcional) além de `data_concertacao` e valida a janela de consulta **somente contra data_declaracao se esta estiver de fato presente no CSV homologado**.
- Se a coluna não existir, a cobertura temporal fica **não comprovada** (`janela_declaracao_verificada_no_csv=False`); jamais filtrar apenas por data de concertação.
- O schema `sio_operacoes` exige a nova coluna; bases SQLite antigas são rejeitadas para migração auditada, sem conversão automática silenciosa.
- O arquivo RAR oficial de especificação da API SIO permanece publicado no site, mas não foi possível baixar e inspecionar seus bytes neste ambiente. Endpoint e formato de exportação **ainda não homologados**.

### Multibanco para Cloud

O `agro_bigquery_stage.py` original aceita um SQLite por vez; os coletores reais costumam usar bancos distintos. A nova camada:
- `src/nivon/agro_consolidar_multibancos.py` reúne até 30 bancos SQLite existentes em lotes JSONL privados, divididos por limite de linhas/bytes, com manifesto de SHA e contagem por fonte.
- Deduplica apenas registros exatos, preserva vintages diferentes, interrompe em conflito de valor para a mesma chave/vintage e **não expõe IDs individuais de operação SIO**.
- `src/nivon/agro_operacao.py` é o ponto de entrada único para **consolidar → verificar integridade de todos os lotes → preparar BigQuery → MERGE opcional**.
- `src/nivon/agro_bigquery_merge.py` substitui o `WRITE_APPEND` direto da etapa live por `LOAD` em tabela intermediária de lote, seguida de `MERGE INSERT-only`, comparação `IS NOT DISTINCT FROM` para valores nulos, validação de schema e IDs de jobs determinísticos. Cada lote recebe limite de bytes faturáveis para query.
- O destino é a tabela de **staging/quarentena** pré-existente, nunca o banco editorial ou os motores de preço. O loader não cria projeto/dataset e somente cria tabela intermediária na nuvem com flags de autorização/custo.

**Contrato operacional de execução sem nuvem (preflight):**

```bash
PYTHONPATH=src python -m nivon.agro_operacao \
  --banco /dados/privados/argentina.sqlite \
  --banco /dados/privados/mercado.sqlite \
  --banco /dados/privados/conab.sqlite \
  --pasta-saida /dados/privados/lotes/2026-10-23 \
  --projeto nivon-data --dataset nivon_stage
```

Pré-requisitos locais: os bancos e o diretório final devem existir e estar privados. Os identificadores `nivon-data` e `nivon_stage` acima são ilustrativos: **verificar os valores reais do projeto/dataset antes de tentar nuvem**. O diretório do lote deve estar vazio; a mesma execução nunca sobrescreve manifestos ou lotes já existentes.

Para autorizar carga real exige-se `--executar-cloud --custos-autorizados --armazenamento-autorizado --licencas-conferidas`, além de ADC/IAM, schema BigQuery pronto e evidência por fonte. NÃO executar com autorização meramente presumida. Em caso de falha no meio de uma carga multishard, os shards anteriores permanecem no BigQuery; consultar jobs por ID antes de nova tentativa, e não reiniciar com outro prefixo sem reconciliação.

O uso de `MERGE` é indicado pela documentação oficial do BigQuery como forma de inserir registros ausentes, e `IS NOT DISTINCT FROM` compara NULLs sem induzir duplicação. **Código e testes por mocks não significam integração cloud real concluída.**

### Bloqueios de implantação e qualidade

- O BigQuery, GCS, Cloud Run e agendamento ainda não foram validados com credenciais/recurso real. Nenhum job cloud de dados foi executado.
- Dados do CEPEA e IMEA requerem verificação específica de licença por operação e canal de coleta; dados publicados no site/uso não comercial não equivalem a direito de redistribuição.
- Dados de SAGyP no portal de dados abertos indicam CC BY 4.0; ainda falta validar bytes download/CKAN e data efetiva de disponibilidade, pois o portal retornou 403 ao navegador de pesquisa.
- DJVE e monitor comercial precisam do esquema de fonte validado. SIO operação declarada não equivale a frete, entrega ou exportação realizada.
- O workflow `.github/workflows/acessos-privados.yml` apresenta falhas em push sem jobs executados; seu diagnóstico permanece separado do job `Testes locais NIVON`. Não concluir integração a partir do resultado do segundo.


## Encerramento da rodada 23/10 — contratos finais de staging e idempotência BigQuery

- Fonte Argentina SIO: `sio_operacoes.data_declaracao` é distinta de `sio_operacoes.data_concertacao`. A primeira verifica a janela de consulta de 180 dias, enquanto a segunda é usada para a referência econômica do contrato; ausência de `data_declaracao` não prova cobertura da janela.
- Stage: `agro_bigquery_stage._FIELDS` e `sql/bigquery/002_agro_fontes_staging.sql` incluem `data_declaracao` opcional, distinta de `data_publicacao_original`. Para SIO com `data_declaracao` não fornecida, marcar `SEM_DATA_DECLARACAO` na qualidade.
- `agro_consolidar_multibancos.py`: consolidação offline de múltiplos SQLite, deduplicação de linhas exatas, lotes limitados a 25 mil registros por padrão, com manifesto e SHA para reconciliação.
- `agro_operacao.py`: comando único `SQLite(s) -> JSONL(s) -> preflight -> MERGE opcional`. Sem flags de autorização, não acessa rede/cloud; com autorização expressa, deve encontrar tabela BigQuery preexistente.
- `agro_bigquery_loader.py` **não usa mais WRITE_APPEND direto**: agora delega ao `agro_bigquery_merge.py`, que realiza LOAD em tabela intermediária restrita a cada lote, seguida de `MERGE INSERT-only` com igualdade NULL-safe. Não apaga vintages nem reenvia lote cujo MERGE tenha sido concluído; falha e preserva evidência quando job parcial não pôde ser conciliado.
- A documentação do GoogleSQL confirma `MERGE`, `IS NOT DISTINCT FROM` e `INSERT` para esse contrato. Esse desenho ainda precisa de homologação com execução real e métricas de cobrança.
- Todas essas alterações estão em PR draft sem merge em main nem deploy. A fonte SIO e as condições de uso permanecem sem homologação técnica de CSV/API (arquivo RAR oficial publicado, mas não legível pelo ambiente). Sem backfill automático ativo.

Proximas etapas (em blocos executáveis, não testes isolados):
1. Confirmar bytes originais SAGyP e uma planilha CONAB real licitamente capturada, com hashes e datas de acesso/edição.
2. Abrir e inspecionar legalmente o arquivo da especificação da API SIO e reconciliar colunas/método de exportação real.
3. Conciliar os importadores CEPEA/IMEA com os direitos/cadências e o histórico do Drive como backfill, não como verdade de atualização.
4. Em GCP real, validar IAM, criar a tabela stage de contrato 002 apenas se autorizada, executar carga pequena com limite de custo, verificar query MERGE e contar duplicatas/frescura; só depois automatizar cloud jobs.
5. Diagnosticar falha pré-job da workflow GitHub `acessos-privados.yml`, que é independente da validação do núcleo.
