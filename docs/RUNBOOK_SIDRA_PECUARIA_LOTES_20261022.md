# NIVON / Inteligência Pecuária — plano de entregas SIDRA

**Última revisão: 22/10/2026 (local MT).** Escopo isolado na PR #22.
**Maturidade: código testado exclusivamente com respostas sintéticas.**
O sistema não possui captura oficial validada da Pesquisa Trimestral do Abate
de Animais e não está autorizado a publicar indicadores de produção ou previsão.

## Prioridades e critérios de aceite

| Ordem | Execução | Evidência de testes | Estado |
|---|---|---|---|
| P0.1 | Sondar HTTPS 1092/1093/1094 sem crawler | Plano sem rede, 6 respostas falsas, HTTP 500, JSON inválido | **Código implementado; HTTP oficial pendente** |
| P0.2 | Processar amostras em lote, variáveis e categorias explícitas | Captura -> normalizador -> auditoria -> historico por corte | **Implementado/testado em sintéticos** |
| P0.3 | Processar as três espécies numa operação | Lote de 3 cadeias, erros de dimensão, direitos, 25 entradas | **Implementado/testado em sintéticos** |
| P1.4 | Preservar histórico, hashes e revisões | SQLite 1 transação, rollback, reimportação, as-of | **Implementado/testado em sintéticos** |
| P1.5 | Consolidar relatório de prontidão | Cobertura BR/UF desconhecida, censuras, revisões, bloqueios | **Implementado/testado em sintéticos** |
| P1.6 | Interface local e governança | CLI subprocess, dry-run, persistência autorizada, path traversal | **Implementado/testado em sintéticos** |
| P0 real | Homologar metadata, direitos, cronologia e respostas IBGE | HTTP oficial, metadados verdadeiros, 3 fixtures autorizadas | **BLOQUEADO por ambiente de consulta** |

Os quatro itens de inferência que não podem ser tomados como verificados
pela ferramenta: autenticidade HTTPS histórica, publicação original,
categorias/unidades oficiais e autorização legal de armazenamento.

## Pipeline implementado

- \`src/nivon/pecuaria_sidra_sondagem.py\`: consultas HTTPS **somente se invocadas
  explicitamente com --rede**. Hosts fixos (apisidra.ibge.gov.br e
  servicodados.ibge.gov.br), sem redirect, proxy ou login, timeout máximo
  de 10 segundos e payloads limitados a 1/2 MB. Sem persistência.
- \`src/nivon/pecuaria_sidra_operacao.py\`: CLI offline que consome manifesto
  e referências a arquivos JSON locais. Prévia é padrão, recusa caminhos
  absolutos, symlinks, path traversal, dados grandes e permissões omitidas.
- \`src/nivon/pecuaria_sidra_lote.py\`: executa pré-validação de até 24
  capturas, normalização 1092/1093/1094, qualidade territorial somente com
  lista oficial explicitamente declarada, seleção de vintages ao corte, e
  relatório JSON sucinto sem linhas brutas.
- \`src/nivon/pecuaria_sidra_arquivo.py\`: função
  \`arquivar_lote_sidra_atomico\` verifica todos os pacotes, abre uma
  transação SQLite, identifica duplicatas e faz **rollback do lote inteiro**
  se alguma captura conflitar com a base. Bancos SQLite continuam locais,
  sob a política de direitos do operador, e **não** são imutáveis contra
  administrador.
- \`src/nivon/pecuaria_sidra_abate.py\`,
  \`src/nivon/pecuaria_sidra_vintages.py\`: normalização de observações,
  símbolos SIDRA (zero vs. censura), calendário 1997+, controle por
  espécie/UF/competência/indicador e prevenção de look-ahead.
- Registro de BOI, SUINO e FRANGO contém o pipeline **desligado**:
  \`scheduled_enabled=false\` e \`operational_enabled=false\`.

## Procedimento de execução

**1. Inspecionar URLs sem rede:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_sondagem --periodo 202602
\`\`\`

**2. Diagnóstico HTTPS somente em rede autorizada:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_sondagem --periodo 202602 --rede
\`\`\`

Se retornar \`FORMATO_PRELIMINAR_CONFIRMADO\`, verificar manualmente
corpo, categorias e unidade contra a documentação oficial. Esse estado
NÃO é homologação de fonte. \`ERRO_NAO_HOMOLOGADO\` não significa
automaticamente indisponibilidade da API para todos.

**3. Preparar manifesto 1.0 fora do repositório público:**

\`\`\`json
{
  "schema_version": "1.0",
  "capturas": [
    {
      "especie": "FRANGO",
      "tabela_sidra": "1094",
      "arquivo_valores": "1094-valores.json",
      "arquivo_metadados": "1094-metadados.json",
      "url_valores": "https://apisidra.ibge.gov.br/values/t/1094/n1/1/p/202602/v/allxp/h/y",
      "url_metadados": "https://servicodados.ibge.gov.br/api/v3/agregados/1094/metadados",
      "publicacao_declarada": "SUBSTITUIR_POR_PUBLICACAO_COM_FUSO",
      "coleta_declarada": "SUBSTITUIR_POR_COLETA_COM_FUSO",
      "dimensoes": {},
      "totais": {},
      "variaveis": {}
    }
  ]
}
\`\`\`

**Os campos em branco são obrigatórios:** devem vir de uma inspeção
real da tabela, não de IDs de testes (\`9999\`/\`8888\` são **fictícios**).
O manifesto acima é ilustrativo e **falhará fechado até ser preenchido**
e acompanhado dos dois JSONs reais autorizados.

**4. Executar prévia offline, sem gravar banco:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_operacao \
  --manifest /dados/sidra/manifesto.json \
  --base-dir /dados/sidra/brutos \
  --corte 2026-10-23T00:00:00-04:00 \
  --confirmar-direitos
\`\`\`

**5. Arquivar apenas após confirmar direitos e contrato dimensional:**

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_operacao \
  --manifest /dados/sidra/manifesto.json \
  --base-dir /dados/sidra/brutos \
  --corte 2026-10-23T00:00:00-04:00 \
  --confirmar-direitos --gravar \
  --banco /dados/sidra/capturas.sqlite
\`\`\`

O arquivo SQLite deve ficar fora do GitHub. O sinalizador
\`--confirmar-direitos\` é **declaração do operador**, não atestado
externo de licença. Reexecução idêntica reaproveita IDs e dados. Divergência
no mesmo instante de coleta é recusada e provoca rollback do lote.

**6. Executar suíte inteira:**

\`\`\`bash
PYTHONPATH=src python -m unittest discover -s tests -v
\`\`\`

Os testes de CLI constam em \`tests/test_pecuaria_sidra_operacao_cli.py\`;
os de pipeline/rollback/sondagem em
\`tests/test_pecuaria_sidra_lote_integrado.py\`. O CI completo é a
evidência canônica após cada HEAD.

## Políticas de dados e liberação

- CEPEA e SCOT permanecem fora deste escopo até autorização/licença de
  consulta, armazenamento e redistribuição; não supor acesso liberado.
- Uma coleta atual não é vintage autêntico de edição histórica.
- Não misturar rebanho anual com abate trimestral, abate federal SIF com
  produção total sob inspeção, nem Brasil com soma das UFs desconhecidas.
- A Pesquisa Trimestral do Abate possui revisões históricas. Documentar
  data de publicação e fonte de edição quando houver dado real.
- JSON arquivado/HTTP 200 não autoriza uso comercial nem publication.
  O pipeline nunca sinaliza \`publicacao_permitida=true\`.
- Sem execução agendada, integração WhatsApp, credenciais, serviços cloud,
  merge ou gasto ativados nesta PR.

### Referências públicas
- Pesquisa e tabelas IBGE: https://sidra.ibge.gov.br/pesquisa/abate/tabelas/
- API Agregados v3: https://servicodados.ibge.gov.br/api/docs/agregados?versao=3
- Esquema/API conceitual independente: https://docs.ropensci.org/ibger/articles/api-concepts.html


## Execução real: constatações de 23/10/2026 e quarentena de values

O bloqueio de conectividade aos **valores** foi parcialmente superado:
**GitHub Actions** conseguiu HTTP 200 real e retornos JSON para as tabelas
1092/1093/1094, no 2º trimestre de 2026. Endpoints da API **v3
metadados** expiraram por timeout no mesmo runner (não prova indisponibilidade
na origem).

**Evidências do runner, sem gravar valores brutos no repositório:**

- [Acesso aos valores das 3 tabelas](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945037846)
- [Identificação de DnC e códigos reais](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945191701)
- [Normalização real Brasil e UFs](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945474689)
- [Diagnóstico de censura e UFs não retornadas](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39945756036)
- [Coletor de quarentena em modo real sem gravação](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946527270)

### Mapeamento observado no endpoint values

O arquivo \`src/nivon/pecuaria_sidra_mapa_observado.py\` contém o mapa
**verificado no recorte nacional 2026-T2**, NÃO homologado para qualquer outra
competência, geografia, variável ou publicação:

| Tabela | Variáveis | Dimensões de classificação | Códigos TOTAL |
|---|---|---|---|
| 1092 bovino | 284 cabeças; 285 carcaças | D4C rebanho; D5C inspeção; D6C referência temporal | rebanho=992; inspeção=118225; referência=115236 |
| 1093 suíno | 284; 285 | D4C inspeção; D5C referência temporal | inspeção=118225; referência=115236 |
| 1094 frango | 284; 285 | D4C inspeção; D5C referência temporal | inspeção=118225; referência=115236 |

Nos seis retornos oficiais \`n1/1\` e \`n3/all\`, filtrados explicitamente
por \`v/284,285\`, o parser já foi executado **com sucesso sem salvar bytes**.
Os relatórios abaixo preservam dados censurados e UFs não retornadas
**sem imputação**:

| Espécie | UFs numéricas por indicador | UFs censuradas por indicador | UFs ausentes |
|---|---:|---|---|
| Bovino | 25 | AP, DF (2) | nenhuma |
| Suíno | 21 | AC, AM, PA, RR, SE (5) | AP |
| Frango | 19 | AC, AL, AM, DF, RN, RR, SE (7) | AP |

Valores numéricos nacionais foram retornados, mas nenhuma soma residual
BR-Estados foi promovida ou homologada, pois ainda há censura/cobertura
não confirmada por metadados v3.

### Novo coletor: values em QUARENTENA, sem fabricar metadados

\`src/nivon/pecuaria_sidra_quarentena.py\` recebe seis respostas HTTPS
oficiais, normaliza em memória, avalia cobertura e pode armazenar
**somente os bytes de values** em SQLite local separado. Não inventa um
JSON de metadados apenas para satisfazer o arquivo anterior
\`pecuaria_sidra_arquivo.py\`.

A primeira execução é sempre **sem rede**:

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_quarentena
\`\`\`

A leitura das APIs, se houver permissão de consulta e condições de rede
apropriadas, é explícita e a **prévia não salva nada**:

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_quarentena \
  --periodo 202602 --rede --confirmar-direitos
\`\`\`

Armazenamento local em quarentena requer uma decisão independente,
\`--gravar\`, permissões e um caminho fora do GitHub:

\`\`\`bash
PYTHONPATH=src python -m nivon.pecuaria_sidra_quarentena \
  --periodo 202602 --rede --confirmar-direitos \
  --gravar --banco /dados/sidra/quarentena-values.sqlite
\`\`\`

Isso **não foi executado com gravação real** no GitHub Actions. O CI
executou apenas prévias reais e testes de gravação em banco temporário com
JSON **sintético**.

- Nenhum agendamento, merge, deploy, WhatsApp ou banco cloud ativado;
- dados em quarentena não alimentam série/histórico CANÔNICO;
- o horário da captura apenas informa a primeira observação, **não**
  a publicação original do IBGE;
- o mapeamento foi observado em 2026-T2 e testado em 2025-T2/2026-T1; outros trimestres exigem confrontação dinâmica dos cabeçalhos, IDs e totais e não são homologados automaticamente;
- o reprocessamento é idempotente por espécie/tabela/trimestre/geografia/
  SHA-256 do bruto e diferentes bytes são capturas distintas;
- banco sem índices/triggers esperados é bloqueado; não há migração
  silenciosa;
- autorização é declaração explícita do operador, nunca prova técnica
  ou jurídica de licença.

Próximas frentes de maior impacto: obter metadados v3 autênticos ou
documentação oficial equivalente; reconciliar cobertura efetiva por
competência; definir regras de publicação de revisões; integrar quarentena
ao banco transacional somente depois de validar direitos e proveniência.

## Continuidade 23/10/2026 — backfill e consulta temporal

**Evidência real:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983108842
GitHub Actions acessou 12 extratos oficiais SIDRA de 2025-T2 e 2026-T1, processando 266 registros numéricos e 62 marcações ausentes/inibidas. Nenhum payload real foi persistido. A data de publicação de cada edição histórica permanece não confirmada.

**Nova implementação:** src/nivon/pecuaria_sidra_backfill.py suporta lotes de 1 a 4 trimestres (6 a 24 GETs quando expressamente habilitados), valida dimensão/variável/competência e faz uma única transação SQLite com rollback para o lote todo.
**Consulta temporal:** recupera somente a última versão arquivada conhecida na data de corte informada; usa primeira coleta comprovada como limite conservador, NUNCA como data histórica da publicação oficial.
**Proteção adicional:** a leitura rejeita resultados potencialmente truncados acima de 500 capturas selecionáveis; requer paginação antes de ampliar essa cota.

### Comandos

Prévia de URLS, sem rede e sem gravação:
    PYTHONPATH=src python -m nivon.pecuaria_sidra_backfill --periodo 202502 --periodo 202601

Consulta HTTPS e prévia, requer permissão de consulta:
    PYTHONPATH=src python -m nivon.pecuaria_sidra_backfill --periodo 202502 --periodo 202601 --rede --confirmar-direitos

Gravação de extratos oficiais em SQLite **somente mediante direitos efetivamente confirmados**:
    PYTHONPATH=src python -m nivon.pecuaria_sidra_backfill --periodo 202502 --periodo 202601 --rede --confirmar-direitos --gravar --banco /dados/sidra/quarentena-values.sqlite

Leitura por data de corte, sem rede e sem escrita:
    PYTHONPATH=src python -m nivon.pecuaria_sidra_backfill --periodo 202502 --periodo 202601 --consultar --especie BOVINO --corte 2026-10-23T16:00:00+00:00 --banco /dados/sidra/quarentena-values.sqlite

Testes E2E: tests/test_pecuaria_sidra_backfill_integrado.py, incluindo revisão capturada em datas diferentes, consulta CLI, ID de variável divergente, mapa temporal alterado, falha HTTP final e rollback SQL.

**Estados:** funcionalidade implementada e testada; metadados v3, comprovação de licença e data histórica oficial continuam pendentes. Não ativado em produção, Google Cloud, WhatsApp ou agendamento.

## Continuidade 23/10/2026 — revisões completas, lacunas e exportação portátil

### Motor de revisões por escopo

- `src/nivon/pecuaria_sidra_revisoes.py`: compara versões inteiras do MESMO recorte espécie/tabela/trimestre/território. Estados `VALOR`, `CENSURADO` e `AUSENTE_NO_EXTRATO` são distintos. Toda captura nova substitui seu recorte territorial por completo; linhas omissas não herdam valores antigos, nem viram zero.
- `consultar_backfill_quarentena` preserva duas visões: `capturas_historicas_no_corte` (todas as versões já conhecidas) e `capturas_conhecidas_no_corte` (apenas a última por trimestre/recorte). O diagnóstico territorial é calculado SOMENTE sobre as versões vigentes.
- `revisoes_observadas`, `total_revisoes_observadas` e `capturas_superadas_no_corte` explicitam mudanças de valor, censura ou desaparecimento, identificando os IDs e SHA-256 de ambas as capturas. A data continua sendo PRIMEIRA COLETA NIVON, não publicação histórica atestada do IBGE.
- `pecuaria_sidra_quarentena.py` impede novas versões conflitantes no mesmo instante por recorte, dentro da transação: nenhuma inserção parcial é mantida.

### Exportação local pronta para futura carga em staging

- `src/nivon/pecuaria_sidra_exportacao.py`: lê SQLite em modo somente leitura, verifica hashes e corte, exige declaração específica de direito de transferência, prepara diretório novo com bytes JSON originais e `manifesto.json`, contendo período, UF/BR, espécie, URL declarada, primeira coleta e SHA-256. A escrita do diretório usa staging temporário e renomeação.
- Não há conexão com Google Cloud Storage/Cloud SQL, upload, bucket, serviço ativado ou despesa. O pacote é transportável apenas após verificação externa das permissões de transferência e da autenticidade dos dados.

**Comando de exportação exclusivamente local:**

    PYTHONPATH=src python -m nivon.pecuaria_sidra_backfill --periodo 202502 --periodo 202601 --banco /dados/sidra/quarentena-values.sqlite --corte 2026-10-23T23:59:00+00:00 --confirmar-direitos --exportar-para /dados/entregas/sidra-quarentena-v1

- O destino deve ser diretório NOVO, com pai existente; não sobrescreve pacotes anteriores, nem publica conteúdo. Depois de gerar, o operador pode conferir SHA-256 dos blobs frente ao manifesto e manter o pacote fora do repositório público.
- A exportação contém TODAS as capturas conhecidas no corte para reconstruir revisões, não somente os valores vigentes. Faltando capturas anteriores, não se pode reconstruir edições nunca observadas.
- Testes E2E: `tests/test_pecuaria_sidra_backfill_integrado.py` verifica UF desaparecida e substituída, alteração de preço/volume inexistente não inventada, revisão numérica, conflito de timestamp, replay, hashes, exportação, falta de permissão, corte anterior e bloqueio de diretório já existente.

**CI verificado:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001123587 — 1.325 testes executados, 0 falhas, 5 ignorados. Nenhuma execução real de armazenamento em nuvem ou captura de novos dados oficiais nesta rodada.

**Pendências de aceitação antes de produção:** P0 homologar metadata v3 (ou documentação primária equivalente), classificação territorial por versão, termos de consulta/retencao/transferencia e calendário de publicação IBGE; P1 integração GCP de staging sem custos não autorizados; P1 aferição da exatidão de revisões retrospectivas com edições capturadas em datas efetivamente diferentes.
