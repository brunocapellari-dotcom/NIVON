# NIVON — execução ANP LPC real, incremental e sem deploy (22/10/2026)

## Escopo de autorização e referência

O operador autorizou **coleta e uso dos dados públicos ANP para finalidade interna não comercial** em 22/10/2026. A ANP permite reprodução sem fins lucrativos com atribuição obrigatória da fonte, conforme seus termos oficiais: https://www.gov.br/anp/pt-br/acesso-a-informacao/termos-de-uso-privacidade-e-seguranca-1 . Esta autorização não inclui venda de serviços que utilizem conteúdo do portal, contorno de proteções, raspagem intensiva, licenças comerciais ou redistribuição sem observar os termos.

Fonte ANP de descoberta de edições, sempre consultada antes de baixar o XLSX:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas

Fonte complementar da série histórica semanal por município:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/serie-historica-do-levantamento-de-precos

Em 22/10/2026, o índice público aponta as semanas 27/09 a 03/10, 04 a 10/10 e 11 a 17/10/2026. A última data de atualização da página **não equivale** à primeira data oficial de publicação de cada edição. Nenhum SHA, preço ou arquivo do portal deve ser inventado.

## Entrega técnica desta rodada

- `src/nivon/anp_lpc_coletor_real.py`: obtém índice ANP oficial e até **3 planilhas XLSX** por execução. Só aceita HTTPS em `www.gov.br`, arquivos explicitamente descobertos no índice e recurso `@@download/file` da própria URL anunciada; sem redirecionamento automático, WAF bypass, varredura por nomes inventados ou APIs desconhecidas. Respostas são limitadas em bytes, MIME e assinatura ZIP; solicitações sucessivas têm intervalo mínimo padrão de um segundo.
- `src/nivon/anp_lpc_staging_real.py`: persiste **somente preços médios agregados municipais de revenda** de Mato Grosso, por diesel e diesel S10 separados, com semana **oficial observada**, SHA-256 do arquivo, URL oficial, hash do índice, captura com timezone, número de postos e classificações de uso. Não armazena nomes/CNPJs de postos. Mantém edições repetidas sob hashes distintos, sem sobrescrever históricos e com trilha de nova captura.
- `src/nivon/cli_coletar_anp_lpc.py`: `--modo rede` para coleta pública explícita, `--modo arquivos` para reprocessamento e backfill offline, `--modo status` para diagnóstico de cobertura/revisões e `--modo consulta` para prévia de tendência municipal. Um lote com uma semana inválida salva outras semanas válidas e reporta **LOTE_PARCIAL**, sem afirmar sucesso total.
- `src/nivon/anp_diesel_pressao_preview.py`: cruza **variação de preços médios de diesel** observada entre duas semanas contíguas, no mesmo município e produto, com o motor existente de sensibilidade hipotética de custo de combustível por tonelada. Não confunde diesel com frete, custo real da transportadora nem repasse ao preço negociado.
- `tests/test_anp_lpc_coleta_real_e2e.py`: bateria integral de três semanas com HTML + XLSX sintéticos, HTTPS emulado, armazenamento RAW imutável, SQLite, reprocessamento idempotente, revisão de mesma semana, falhas parciais, falta de semana, status QA, CLI e cenário de custo rodoviário. `validar-anp-lpc-fixtures` foi ampliado no workflow existente; não há novo agendamento, nem alteração para `push`.

A transição ao banco **homologado** `anp_semanal_store.py` continua controlada pelas atestações existentes. A classe `REAL_PRELIMINAR_NAO_HOMOLOGADO` é **isolada** em tabelas próprias e **não** aparece em `consultar_preco_semanal`. Dados preliminares podem ser usados apenas em estudos internos de qualidade/sensibilidade, sempre com rótulo e proveniência. Não promover automaticamente para preço atual validado ou relatório público.

## Operação real (quando existir rede com acesso à ANP)

Pré-requisitos: Python 3.11, `openpyxl==3.1.5` e pasta privada local **fora do controle de versão**. Sem chave/API paga.

```bash
python -m pip install --no-input 'openpyxl==3.1.5'
mkdir -p data/anp_lpc/raw
PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo rede --ano 2026 --ultimas 3 \
  --db data/anp_lpc/staging.sqlite --raw-dir data/anp_lpc/raw
```

A saída JSON informa fonte, SHA do índice, períodos, quantidade de linhas, edições novas, capturas, falhas e auditoria de qualidade **sem expor preços**. Lotes parciais têm código de saída 2; o banco preserva semanas processadas com êxito e permite reprocessamento idempotente.

```bash
PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo status --db data/anp_lpc/staging.sqlite

PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo consulta --db data/anp_lpc/staging.sqlite \
  --municipio SINOP --produto 'DIESEL S10'
```

Para arquivos já autorizados, criar uma pasta com o HTML real do índice (`indice.html`) e as planilhas nomeadas exatamente conforme os links daquela página. Reprocessar sem rede:

```bash
PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo arquivos --ano 2026 --ultimas 3 \
  --indice caminho/indice.html --pasta-arquivos caminho/planilhas \
  --db data/anp_lpc/staging.sqlite --raw-dir data/anp_lpc/raw
```

As datas persistidas de captura no modo arquivos indicam **o processamento realizado pelo NIVON**; não se apresentam como data de publicação original nem como primeiro download feito no passado. Se for necessário comprovar uma data passada, os metadados de captura deverão ser obtidos de um log externo confiável.

## O que foi realmente verificado

As páginas públicas da ANP foram pesquisadas e identificadas; **a extração dos XLSX não foi possível no ambiente da conversa** por erro de resolução DNS ao conectar em `www.gov.br`. Não classificar isso como falha do portal e não promover amostras fictícias. Os arquivos não foram enviados ao repositório nem ao Google Cloud. Código e testes E2E foram adicionados à PR #42. Uma execução real end-to-end dependerá de um runner com acesso autorizado à rede e conferência do layout verdadeiro. Se o XLSX real diferir da aba `MUNICIPIOS` ou cabeçalho na linha 7, o coletor falhará fechado, registrará a divergência e exigirá adaptação baseada no arquivo oficial, não em suposição.

## Próximos gates objetivos

1. Executar uma vez em runner com HTTPS da ANP acessível, sem proxy que contorne bloqueios, guardar os três hashes e verificar layout de cada semana verdadeira.
2. Obter 3 semanas reais, confirmar número de municípios, diesel vs S10, base de preços, origem e disponibilidade; registrar casos onde o município não foi pesquisado (sem imputação). Corrigir parser se houver mudança real de esquema.
3. Executar coleta incremental numa segunda janela: `edicoes_novas=0` para arquivos idênticos e captura adicional; quando a ANP substituir um XLSX, conservar ambos os hashes e marcar a revisão.
4. Definir cadência e infraestrutura apenas quando validados acesso HTTPS, armazenamento durável e custos; **nenhum agendamento foi ativado**.
5. Integrar o estágio real homologado no produto final somente depois da aprovação operacional e avaliação de uso/atribuição; não contornar a política de atestações, chave e revogação existente.

A `.gitignore` atual exclui `data/`, `*.sqlite*`, `*.xlsx` e credenciais. **Não versionar bytes RAW, preços municipais reais ou segredos em commits, logs ou discussões públicas.** Fonte mínima para qualquer publicação autorizada: *Agência Nacional do Petróleo, Gás Natural e Biocombustíveis (ANP), Levantamento de Preços de Combustíveis, edição e semana oficiais, com link à origem*.


## Inventário adicional: compilação histórica do Google Drive

Foi encontrado no Drive conectado o arquivo **`DIESEL ANP.xlsx`**, criado em 10/08/2026, com 299.565 bytes, localizado na pasta `ANP`. A leitura tabular permitiu inspecionar **4.286 linhas estruturadas** e **52 linhas não classificáveis pelo mesmo esquema** (aparentemente trechos de outras abas/resumos, sujeitos a confirmação no XLSX original). Cobertura identificada das linhas estruturadas: **02/01/2022 a 01/08/2026**, **55 meses de início de semana**, **1.615 linhas de Mato Grosso**, combustíveis `OLEO DIESEL` e `OLEO DIESEL S10`, sem duplicidade aparente na chave data inicial + data final + estado + município + produto. A planilha contém outras UFs e não serve como série municipal brasileira completa.

Arquivo de origem: https://docs.google.com/spreadsheets/d/1cD1QFFgdA3NzaiFkupFRjHjlwxW3ElcJ/edit

**Governança:** é uma **compilação derivada presente no Drive**, não um arquivo LPC semanal RAW validado diretamente contra a ANP. Não atribuir a ela atualidade outubro/2026, não promover a fonte canônica, nem incorporar os dados de 2022–2026 como se fossem registros comprovados pelo novo coletor. A nova coleta real identifica versões oficiais e poderá servir para reconciliação futura dessas amostras históricas. A planilha foi consultada, **não foi copiada integralmente para o repositório ou banco de produção**. A contagem acima é de linhas reconhecidas no conteúdo textual fornecido pelo Drive, não de XLSX bruto verificado por ZIP e openpyxl.


## Descoberta oficial revisada em 23/10/2026 — quebra real de nomenclatura

Ao seguir os links efetivamente publicados no índice da ANP, foi identificada uma variação **real** da grafia do nome da planilha da semana 11/10 a 17/10/2026:

| Semana oficial | Nome no link da ANP | Resultado da revisão |
| --- | --- | --- |
| 27/09 a 03/10/2026 | `resumo_semanal_lpc_2026-09-27_2026-10-03.xlsx` | Formato ISO antigo |
| 04/10 a 10/10/2026 | `resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx` | Formato ISO antigo |
| 11/10 a 17/10/2026 | `resumo_semanal_lpc_2026_10_11-2026_10_17.xlsx` | **Underscores dentro da data e hífen entre datas** |

Página de descoberta oficial:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas

Os links se referem ao mesmo conjunto temático; a mudança de nome **não** implica mudança de layout XLSX. Isso será verificado apenas com os bytes. Em 23/10/2026 a ferramenta de consulta web conseguiu alcançar os links diretos mas não extrair arquivos XLSX devido à restrição do leitor web para `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. O ambiente de execução de Python não possui resolução de DNS para `www.gov.br`. Portanto, **o layout de uma edição real e a integração real permanecem não homologados**.

**Correção aplicada:** `anp_indice_lpc.py` aceita estritamente as duas grafias realmente observadas, valida exatamente 7 dias por semana e obtém os intervalos do próprio link do índice, não de um calendário inferido. `anp_lpc_coletor_real.py` agora solicita **a URL XLSX direta listada pela ANP**. O código anterior acrescentava `/@@download/file` sem o sufixo ser anunciado, o que podia transformar links oficiais válidos em erros HTTP ou baixar recurso diferente. A restrição de domínio/caminho/arquivo foi mantida e reforçada. Foram adicionados contratos de descoberta e um cenário E2E para a grafia mais recente; testes de regressão HTTP foram ajustados para URLs diretas.

**Próximo gate:** rodar os testes E2E no HEAD novo e baixar as três edições verdadeiras com runtime que possa ler XLSX, sem criar caminhos artificiais ou presumir publicação.
