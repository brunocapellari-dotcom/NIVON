# NIVON — SISFOGO/IBAMA ROI público (integração de contrato, 21/10/2026)

## Fonte oficial e interpretação

- Catálogo governamental **v1.0 de 27/08/2026**: https://www.gov.br/conecta/catalogo/apis/registro-de-ocorrencia-de-incendio-florestal-roi
- **Produção**: \`GET https://sisfogo.sistema.gov.br/api/v1/roi/publico?page=1&size=10\`
- Parâmetros: \`page\` inicia em 1 (default 1) e \`size\` tem máximo de 500 (default 10); documentação indica até **10 requests/segundo**, status HTTP 429 em excedente.
- **Sem credencial/token** e **somente leitura**, segundo o catálogo oficial. Endpoints com \`hom.ibama.gov.br\` e \`ocp-dev.ibama.gov.br\` são de homologação/desenvolvimento. Não usá-los como produção nem persistir seus registros.
- Contém apenas **ROIs FINALIZADOS**, inclusive retificados depois de concluídos, de **órgãos participantes** do SISFOGO; ROIs em andamento ou com retificação em curso não entram. Não é censo completo, alerta de fogo ativo nem sensor de foco de calor.
- O usuário forneceu exemplo de Swagger com \`pagina=0\`, \`tamanhoPagina=0\`, \`totalItens=0\` e \`itens\` preenchido. Esse exemplo não é resposta operacional válida nem prova de volume real. O contrato usa a regra oficial de \`page=1\`.

## Código e contrato de dados

\`src/nivon/sisfogo_roi.py\`:

- \`planejar_pagina_roi(page, size)\`: monta URL de consulta única autorizada; **não executa HTTP**.
- \`normalizar_pagina_roi(payload, page, size, coletado_em)\`: recebe somente bytes já obtidos, valida paginação, JSON sem chaves repetidas, UUID, status \`FINALIZADO\`, flag de retificação, coordenadas, bioma/UF, timestamps com fuso, área estimada em ha e dados de combate com discriminação.
- \`conferir_lote_paginas(paginas)\`: confere total/páginas e ausência de IDs duplicados em lote pré-coletado. **Não comprova snapshot remoto atômico**; atualizações durante paginação podem deslocar ROIs mesmo quando as contagens batem.

Principais colunas:

| Campo NIVON | Fonte | Governança |
| --- | --- | --- |
| \`roi_id\` | \`id\` UUID | identidade canônica do registro, NÃO da área espacial |
| \`numero_roi\` | \`numeroRoi\` | identificador operacional complementar |
| \`retificado\` | \`retificado\` | preservar versões, nunca sobrescrever silenciosamente |
| \`ultima_atualizacao_em_utc\` | \`dataHoraUltimaAtualizacao\` | data de alteração informada pela origem, NÃO publicação |
| \`referencia\` | \`datasIncendio.dataInicioIncendio\` (senão detecção) | início **estimado** do incêndio; não é data de coleta |
| \`competencia\` | mês da referência, quando existe | \`null\` quando não há início nem detecção |
| \`publicacao\` | não informada pelo esquema | manter \`null\`; sem look-ahead em backtests |
| \`coleta\` | data/hora de aquisição transmitida ao parser | timezone obrigatório |
| \`latitude/longitude\` | \`localIncendio\` | ponto de ocorrência, NÃO perímetro ou polígono |
| \`codigo_ibge\` | não disponível | \`null\` até cruzamento inequívoco com IBGE |
| \`area_queimada_estimada_ha\` | \`informacoesPosIncendio.estimativaAreaQueimada\` | estimativa do ROI; não área agrícola comprovadamente perdida |
| \`vegetacoes_atingidas\` | descrição das vegetações no ROI | evidência reportada, não mapa classificado |
| \`houve_combate\` | \`houveCombate\` | não deduzir números de brigadistas a partir de ausências |

Em caso de ROI com mesmo UUID e atualização diferente, guardar ambas as versões após homologar persistência. Nunca somar registros diários \`MANTIDO\` como equipes únicas, nem contar frentes como incêndios distintos. Não confundir publicação posterior de ROI finalizado com novo foco em tempo real.

## Aplicação ao NIVON

Fonte **P1 / CLIMA** com uso em **risco de incêndios, histórico de ocorrências, exposição agropecuária e logística**. Cruzar apenas com localização e referência válidas. Complementar com INPE/BDQueimadas, meteorologia INMET/CPTEC, umidade e seca, CAR/uso do solo quando permitido e dados fundiários oficiais — sem extrapolar impacto causal ou perda financeira.

A área total reportada pelos ROIs não pode ser extrapolada como total nacional queimado, já que somente participantes registram os dados.

## Gates antes de habilitar operação

1. Consultar **uma página pequena de produção** (\`page=1&size=1\`) em executor autorizado com rede, registrar status 200, Content-Type JSON, campo \`pagina\`, \`tamanhoPagina\`, horários, nulls e hash. Nesta sessão, o ambiente não resolveu o domínio remoto.
2. Conferir termos da API para **coleta, armazenamento, uso não comercial e divulgação**. O antigo [conjunto Sisfogo/ROI no portal IBAMA](https://dadosabertos.ibama.gov.br/dataset/sisfogo-roi) é marcado CC Atribuição, mas não assumir automaticamente a mesma licença para a nova API sem verificação.
3. Implementar aquisição rate-limited e com retries limitados para 429/5xx, timeouts e armazenamento privado, com logs e checksums. Não iniciar backfill irrestrito.
4. Homologar amostras reais com campos opcionais, volumes, datas e estabilidade de paginação. Se a API mudar durante as páginas, detectar duplicação e reconsultar de forma conservadora.
5. Implementar vintage por \`roi_id\` + \`dataHoraUltimaAtualizacao\` + hash; testar reprocessamento, idempotência, backup/restore e leitura point-in-time.
6. Medir cobertura geográfica e temporal com outros dados oficiais; definir política de lag e uso editorial. Só depois habilitar coletor por fonte e agendamento controlado.

**Situação do incremento:** fonte, rota, parser e testes versionados; \`enabled=false\`, \`collection_authorized=false\`, \`runtime_enabled=false\`, \`scheduled_enabled=false\`. Sem deploy, sem custo, sem acesso live confirmado, sem publicação operacional. A suíte de testes do PR deve confirmar compilação e casos sintéticos.

Rodar:

\`\`\`bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon.catalogo_fontes --resumo
PYTHONPATH=src python -m nivon.rotas_coleta --resumo
\`\`\`
