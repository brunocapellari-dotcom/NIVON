# Plano de implementação e critérios de conclusão — NIVON

Estado: **IMPLEMENTANDO**, não homologado. Auditorias de 16/10/2026: GO COM CONDIÇÕES, nenhum P0 documental.

## Prioridade 0 — base reprodutível

- [x] Repositório público sem dados reais restritos ou credenciais.
- [x] Núcleo matemático independente: consumo, checagem de margem CEPEA, ANTT NCM amostral e contratos portuários.
- [x] Ingestão de CSV **local** com contrato obrigatório e proveniência SHA-256.
- [x] Balanço físico de safra/ano civil com conservação e decomposição de demanda, sem duplicar componentes.
- [x] Suíte de **119 testes sintéticos aprovada no GitHub Actions**, commit 76cb2a5e e posteriores, conforme logs do PR #1. Revalidar após toda alteração.
- [ ] Inspecionar o diff, direitos por fonte e segurança antes de merge. Runner padrão público gratuito já confirmou CI; ainda falta revisão independente de release.

**Aceite:** `python -m unittest discover -s tests -v` retorna sucesso com Python >=3.11, em ambiente limpo, sem segredos e rede; import `nivon` sem qualquer GCP/Hermes/Holding.

## Prioridade 1 — dados reais governados, sem publicação de arquivos

**CONAB — CATÁLOGO DE FONTES ADICIONADO:** identificação offline das cinco planilhas oficiais de séries de soja e milho, com seis testes sintéticos; arquivos e URLs descritos em `config/fontes_conab_historicas.v1.json`. **Ainda não existe parser XLS homologado, coleta numérica ou série histórica ingerida.** O milho Total não deve ser somado novamente à primeira/segunda/terceira safras. Necessário validar direitos por operação, edições, cabeçalhos e unidade e introduzir `SOURCE_LAG` em atraso.

**Sindirações/ABIOVE:** registrar termos por finalidade e permitir somente operações habilitadas; recortes de ração e macroingredientes compõem consumo interno já existente, não soma adicional. Séries devem ter edição/vintage. Se restritos, manter conector PENDENTE e usar alternativa licenciada.

**MAPA SIPEAGRO — COLETA REAL E HISTÓRICO LOCAL EXPERIMENTAL:** CSV aberto licenciado CC Attribution foi lido integralmente em execução efêmera do GitHub; 18.003 linhas, 2.029 registros filtrados (Ativo + Fabricante + Alimentação Animal + Ração), 1.168 municípios. Cabeçalho de nove colunas e categorias amostrais inspecionados. Nenhum CPF/CNPJ/nome foi persistido ou divulgado; somente agregado com validação anti-identificadores foi publicado como artefato temporário de 3 dias. Falta validar alias/código IBGE, vigência, recaptura histórica e distinção por espécie de criação. **Não é capacidade ou consumo**. Implementado `src/nivon/historico_municipal.py` com SQLite de edições deduplicadas por SHA-256 e múltiplos eventos de coleta; 8 testes sintéticos em CI. Ainda não há armazenamento persistente em nuvem, backup/restore, nem coleta agendada.

**ANTT — PENDENTE DADO REAL:** obter/exportar base oficial detalhada e verificável, com cobertura NCM e terminal por município. A entrada CSV e a junção com agregado MAPA estão implementadas e testadas apenas sinteticamente; não confundir isso com volumes medidos de MT. Primeiro testar arquivos oficiais e documentação. NCM/MDF-e é amostral; registrar volume com NCM e cobertura quando disponível. Não utilizar endpoint interno Power BI como API oficial sem verificação. Considerar carga própria. Classificar TRANSBORDO_PROVAVEL/CONSUMO_POTENCIAL/AMBIGUO/SEM_EVIDENCIA; preservar todas as linhas.

**Aceite:** para cada fonte, registrar URL, direitos por operação, arquivo analisado fora do GitHub, campos, validações, quatro datas, hash, rejeições e reconciliação com publicação oficial.

## Gate imediato de armazenamento

- [x] Histórico SQLite local, apenas de geografia agregada MAPA, com edições imutáveis por hash, registros de coletas repetidas e consultas as-of.
- [ ] Armazenamento durável independente do notebook e backup/restauração testados; **não depender do artefato de 3 dias como base definitiva**.
- [ ] Índice cronológico com publicação/referência reais quando fornecidas, sem inventar datas; auditoria de direitos e minimização de dados.
- [ ] Automatização de horário de coleta aprovada com tratamento de indisponibilidade e idempotência; não ativar fontes ainda bloqueadas.

## Prioridade 2 — engenharia portuária

- Reutilização preferencial de parsers puros do AgroLog mediante revisão jurídica de proveniência/licença; nunca importar dependências em BigQuery/Cloud Run.
- Dez portos nacionais cadastrados, todos sem homologação na v0.1.
- Uma ficha por porto (fonte, formato, identidades, datas, produtos, volume, acesso, parser, frescor).
- Parser por formato; para cada porto habilitado, exigir >=3 aquisições reais em dias diferentes, contagem confrontada com documento, testes de layout alterado, deduplicação de escala preferencialmente por DUV, e status programado x realizado separado.
- Tubarão requer autorização Vale ou alternativa legítima com campos menores.
- AIS contínuo/ETA próprio/filas somente quando houver histórico, cobertura e infraestrutura explícitos; uma coleta local periódica não é observação contínua.

## Prioridade 3 — inteligência e previsões

- Consumo: CAGR 3–5 anos cenário principal, última taxa como sensibilidade, horizonte inicial <=2 anos e comparação com projeções institucionais.
- Indústria: parâmetros CEPEA de margens; oferecer balanço físico somente com coeficientes de rota e umidade física compatíveis.
- Soja/milho: balances Brasil e MT; para MT conservar movimentos interestaduais e evitar declarar destino final só pelo município.
- Diesel, algodão, bovinos, açúcar, trigo, sorgo e fertilizantes: contratos e motores por domínio, evoluindo sem duplicar o núcleo.
- Backtest walk-forward anual CAGR versus baseline último valor já implementado/testado com séries sintéticas. Modelos só recebem status VALIDADO após vintages as-of por fold, fonte real e comparação robusta fora da amostra.

## Prioridade 4 — operação e interface

- Primeira interface útil somente após dados reconciliados e API com autenticação mínima quando exposta.
- Primeiro uso local **é apenas desenvolvimento**. O objetivo final do projeto é operar em nuvem, independente do notebook, dentro de serviços gratuitos e cotas verificadas; essa transição exige decisão técnica, testes de segurança, persistência e custo e não pode ser prometida 24/7 sem infraestrutura aprovada.
- Nenhum deploy, uso de credencial, fonte restrita ou serviço pago antes de gate correspondente.
- Backup e restauração, saúde de fontes, logs sem payload sensível, testes de segurança e go-live com evidências.

## Bloqueadores de go-live

Não declarar final se falta fonte para dado exibido, CI/testes suficientes, ingestão real homologada, direitos, integridade dos balanços, backup/restore, política de segurança ou controle de custos.

A aprovação metodológica externa não valida o software automaticamente.

## Evidências recentes de CI e dados

- CI de unidade e integração sintética: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39000174173
- Primeiro snapshot integral do MAPA com dados agregados: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/38999841523
- Agregado municipal sem identificadores publicado como artefato temporário: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39000042055
- Cadastro municipal derivado passa a ser entrada alternativa do `analise_local`, testada com JSON sintético.

**Nenhum desses resultados homologa fluxos reais da ANTT, produção de ração ou movimentos portuários.**

## Execuções recentes

- Testes do histórico SQLite: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39039872966
- Testes de identificação das séries CONAB: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39039983616
