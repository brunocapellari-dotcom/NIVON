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
