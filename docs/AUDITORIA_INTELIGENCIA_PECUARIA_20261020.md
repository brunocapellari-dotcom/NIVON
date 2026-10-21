# NIVON — Auditoria e plano executivo da Inteligencia Pecuaria

Data de corte: 2026-10-20. Base: feat/fontes-historicas-motores-cientificos-20261019 (PR #9 empilhada sobre PRs #3/#1). Branch: feat/pecuaria-inteligencia-20261020.

## Evidencia e maturidade

- Bovinos: frentes existentes BOI e BEZERRO registram rendimento de carcaca, relacao de troca e identidade contábil de rebanho; nenhum ciclo completo ou preco previsto homologado.
- Aves e suinos: normalizador offline para SIDRA 1094 / 1093 em cadeias_adicionais.py; peso medio de carcaca, simulacoes de custo/margem, alertas qualitativos, backtest CAGR genérico. Nenhuma serie oficial de abate foi persistida e versionada para estas frentes por esta branch.
- Todas as tres cadeias: direitos, esquema historico da fonte e validacao de dados reais nao concluidos; nenhum scheduler, distribuicao comercial ou sinal probabilistico autorizado.
- A infraestrutura catalogada nao constitui captura de dados efetiva. Revisoes anteriores a uma primeira coleta nao podem ser reconstruidas como vintages de publicacao sem edicoes historicas autenticas.

## Entregas desta branch

- pecuaria_ciclos.py: simulador bovino por arroba de CARCACA, custo de reposicao e ciclo de engorda; simulador frango por ave alojada; simulador suino em terminacao; ração por formulacao explicitamente identificada.
- pecuaria_mercados.py: series separadas para BOI_GORDO (BRL_ARROBA_CARCACA), BEZERRO (BRL_CABECA), FRANGO_VIVO e SUINO_VIVO (BRL_KG_VIVO); timestamp com fuso, fonte, praça, hash, publicacao e coleta; resolucao de revisoes por ultimo vintage disponivel no corte.
- Tendencia OBSERVADA: mediana de tres variacoes homomes interanuais exigindo 15 meses contiguos. Nao confundir com PREVISAO.
- Baselines para futuro: walk-forward mensal comparando naive sazonal anual contra persistencia mensal; exigir >=12 folds, availability em cada cutoff e erro mensurado. Continuam nao homologados: nenhum intervalo de confianca, probabilidade, ensemble ou receita projetada.
- Nenhum modulo reimplementa coleta ou altera o contrato editorial do briefing.

## Plano de dados — fontes canonicas, sem nova fonte da verdade duplicada

Catalogos de operacao a preservar: config/fontes_nivon_master.v1.json, config/rotas_coleta.v1.json e config/matriz_produtos_indicadores.v1.json. Identificadores abaixo devem ser reutilizados e corrigidos, NAO duplicados.

| Prioridade | Fonte/dataset | Uso por cadeia | Trabalho objetivo | Gate |
| --- | --- | --- | --- | --- |
| P0 | IBGE SIDRA 1092 / IBGE_ABATE | bovino: cabecas, carcaças, sexo e tipo por recorte disponivel | confirmar API variaveis/periodos e amostras reais; normalizar por BR/UF, civil/trimestre | publicar/armazenar permitido por operacao |
| P0 | IBGE SIDRA 1093 / IBGE_ABATE_SUINO_1093 | suinos: abate inspecionado e carcaça | confrontar API, variaveis, unidades e revisoes | parser OFFLINE nao significa conector |
| P0 | IBGE SIDRA 1094 / IBGE_ABATE_FRANGO_1094 | frango: abate inspecionado e carcaça | mesmo processo, unidades KG/T explícitas | nao extrapolar a plantel |
| P0 | IBGE PPM / IBGE_PPM | rebanho bovino/suino e galinaceos | registrar estoque em referencia anual, especie/categoria/UF/municipio quando suporte | PPM nao e fluxo de abate; galinaceos nao sao so frangos de corte |
| P0 | MAPA PGA-SIGSIF / catalogo existente | tres especies: abates SIF e categorias | mapear relatorios CSV, modalidade publica, diferenciar cobertura MAPA do IBGE | nao somar SIF e IBGE |
| P0 | MDIC Comex Stat / MDIC_COMEX_NCM | carne bovina, aves, suina e cortes | NCM versionada por ano, sentido, destino, volume, FOB, revisoes | peso liquido de produto != equivalente carcaca |
| P1 | CEPEA_BOI / CEPEA_FISICO, SCOT_PECUARIA | boi, bezerro, aves e suinos quando licenciados | obter direitos e metadados de series, praca, regime e periodicidade | uso comercial/redistribuicao bloqueado ate aprovacao |
| P1 | EMBRAPA CIAS, ABPA_FRANGO_SETOR, ABPA_SUINO_SETOR | dietas, conversao, custos e balancos setoriais | integrar metodologias, datas e autorizacoes de cada publicacao | sem tratar indicadores como registro individual |
| P1 | USDA PSD / FAO FAOSTAT | comparacao de oferta, demanda e comercio internacional | normalizar unidades, ano comercial e series por revisao | coerencia temporal, metodologia |
| P1 | MAPA/WOAH sanidade | febre aftosa, influenza aviaria, PSC/PSA e restricoes | registrar evento, confirmacao, incidencia, geografia, medida oficial e revogacao | alerta nao vira embargo ou perda quantificada |
| P1 | milho, farelo soja, diesel, frete do nucleo NIVON | custos variaveis das tres cadeias | alinhar mesma praca, referencia, qualidade, unidade, prazo | nao converter cotacao em compra executada |

Fontes oficiais para verificacao:
- https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ (1092 / 1093 / 1094)
- https://dados.agricultura.gov.br/pt_BR/dataset/servico-de-inspecao-federal-sif
- https://www.gov.br/agricultura/pt-br/assuntos/inspecao/produtos-animal/sif
- https://www.embrapa.br/en/web/suinos-e-aves/cias/custos/icpsuino
- https://comexstat.mdic.gov.br/
- https://apps.fas.usda.gov/psdonline/

## Modelos futuros, SEM prometer resultados sem series reais

1. **BOVINO**: coortes vaca-matriz/cria/recria/engorda, nascimentos, mortalidade, retencao/descarte de femeas, oferta futura por lag biologico e cenarios de confinamento/pasto. Exigir fontes reais para pesos e eventos sanitarios; evitar transformar PPM anual em rebanho mensal ficticio. Precos boi/bezerro por praca, B3 e spread/reposicao.
2. **FRANGO**: alojamento de pintos, ciclo curto e idade de abate, mortalidade, peso medio, conversao por fase, milho/farelo e capacidade frigorifica. Validar dados primarios de alojamento ou usar somente cenario condicional, nunca estimar plantel com abate de forma determinista.
3. **SUINO**: matrizes/coberturas, partos, desmamados, creche/terminacao, perdas e defasagens especificas, indices tecnicos e exportacoes. Rebanho anual nao e animais disponiveis imediatamente.
4. **MERCADO**: modelos por especie, unidade e praca; sazonal naive, persistencia, regressao com insumos e mercado externo, quantis e classificacao ALTA/BAIXA/ESTAVEL/INDETERMINADA somente apos walk-forward com datas de disponibilidade e dados suficientemente longos. Relatar MAE/RMSE, ganho sobre baseline, cobertura e calibracao; vetar probabilidades sem calibracao externa.
5. **INTEGRACAO**: contratos consumiveis pelo IVO, comercio, mercado e logistica com direitos, fonte, 4 datas (competencia, referencia, publicacao, coleta), unidade, UF/praca, vintage, hash, status observado/inferido/estimado/projetado. Editorial agricola nao deve receber pecuaria automaticamente.

## Gatilhos de homologacao

- Prova de direitos para leitura/coleta/armazenamento/transformacao/redistribuicao por dataset.
- Fixture real com metadados e layout legitimamente permitido, backfill e comprovacao de revisoes.
- Tres extracoes em datas de atualizacao diferentes, persistencia e backup/restauracao, idempotencia, logs.
- Residuos fisicos/biologicos explicados; previsao walk-forward com baseline e nao-leakage.
- Revisor independente e checks CI; sem CI verde e amostra real => CODE_TESTED_SYNTHETIC_ONLY.
- Sem deploy, agendamento, merge, envio WhatsApp, custo ou novos direitos presumidos.

Reproduzir testes sinteticos: PYTHONPATH=src python -m unittest tests.test_pecuaria_ciclos tests.test_pecuaria_mercados


## Continuidade 20/10/2026 — contrato JSON SIDRA offline

### Evidências públicas de metodologia (sem confirmação de API de valores)
- Página de tabelas IBGE: https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ — 1092 bovinos, 1093 suínos, 1094 frangos; dados mensais **dentro** da pesquisa trimestral, não somar total de trimestre e meses.
- Metodologia IBGE: https://www.ibge.gov.br/estatisticas/economicas/servicos/9203-pesquisas-trimestrais-do-abate-de-animais.html — universo do abate **formal** sob inspeção federal, estadual ou municipal; abate informal não é estimado nessa pesquisa.
- Norma pública MAPA sobre SIDRA 1092: https://www.gov.br/agricultura/pt-br/assuntos/sustentabilidade/planoabc-abcmais/abc/sinabc/plataforma-abc/capitulos-portugues-metodologia/capitulo-02-informacoes-sobre-a-metodologia-do-painel-de-terminacao-intensiva-ti.pdf — diferencia animais/carcaças, mês 1/2/3, sexo/categoria e inspeção; este contrato **não** substitui missing/censura por zero.
- Errata histórica IBGE referente ao SIDRA 1094, 05/05/2023, revisões 2008–2022: https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9203-pesquisas-trimestrais-do-abate-de-animais.html — snapshot atual não é evidência de vintages retroativos.

### Artefatos
- \`src/nivon/pecuaria_sidra_abate.py\` — parser de bytes JSON salvo localmente, sem rede. Exige mapeamento EXPLÍCITO de DnC para territorio/periodo/variavel/referencia_temporal/inspecao e rebanho apenas em bovinos, mapa de IDs de variáveis e IDs de categorias TOTAL. Detecta dimensão não declarada, variável porcentual, unidade incompatível, soma indevida de categorias, períodos não trimestrais e duplicata; censuras são separadas, nunca zero. Retorna observações canônicas, pares incompletos, SHA256 real do bruto, edição declarada e status não homologado.
- \`tests/test_pecuaria_sidra_snapshot.py\` — cenários totalmente sintéticos. IDs 9999/8888 e códigos 0 de total são INVENTADOS para prova de contrato; **não representam códigos oficiais do IBGE**.
- \`config/motores_inteligencia.v1.json\` e \`registro_motores.py\` — parser incluído nas frentes BOI, FRANGO e SUINO, com execução operacional ainda desligada.
- Dataset existente \`IBGE_ABATE\` corresponde à tabela bovina 1092 em escopo genérico; **não criar dataset 1092 duplicado** antes de reconciliação pelo diretor da plataforma. \`IBGE_ABATE_FRANGO_1094\` e \`IBGE_ABATE_SUINO_1093\` são os IDs canônicos preexistentes.

### Validação REAL ainda pendente — limite material
- As URLs \`apisidra.ibge.gov.br/values/t/1092\`, 1093 e 1094, e o serviço v3 de metadados, não puderam ter resposta aberta/verificada neste ambiente. Não se atribuir IDs verdadeiros de variáveis/categorias, ordenação D1C...DnC ou unidade MN exata sem capturar ao menos uma amostra autêntica.
- Para homologar: resolver endpoint HTTPS real e direitos; arquivar somente material autorizado fora do repositório público; registrar prova de download e datas de publicação/coleta, inclusive horário e fuso; confirmar layout/códigos e unidade por espécie; adicionar fixture de estrutura real saneada sem dados sensíveis; executar parser no arquivo real; reconciliar totais nacionais por trimestre com PDF/publicação IBGE; executar retrospectivas e análise de revisões históricas.
- Não somar N1 (Brasil) com N3 (UF) nem subcategorias com totais. Não tratar código de missing como zero. O total físico brasileiro e o total das UFs podem divergir por confidencialidade e revisões: diagnosticar, não corrigir sem fonte.
- A assinatura \`status_fonte\`/\`operacoes_autorizadas\` é um gate explícito, não atestado de licença. PENDENTE e falta de direito bloqueiam leitura/armazenamento. Nenhuma fonte, cron ou publicação habilitada.

**Próxima tarefa executável:** verificar resposta de metadados/valores oficiais SIDRA e direitos aplicáveis, mapeando IDs e categorias por tabela/edição; usar arquivo autêntico autorizado para teste e guardar hash/vintage. Depois ligar observações verificadas a séries revisáveis com corte de publicação e modelos por espécie. Sem essa prova, o parser fica CODE_TESTED_SYNTHETIC_ONLY.

## Continuidade 21/10/2026 — correção crítica de cobertura territorial SIDRA

### Evidência pública e limite de confiança
- Fontes oficiais: https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ e https://www.ibge.gov.br/estatisticas/economicas/servicos/9203-pesquisas-trimestrais-do-abate-de-animais.html — 1092 bovino, 1093 suíno, 1094 frango e resultados do 2º trimestre de 2026.
- Catálogo independente, não oficial: https://quantilica.com/fish/tabelas/1092/numero-informantes-quantidade-peso-total-carcacas-bovinos-abatidos-mes-trimestre-tipo-rebanho-tipo-i — mostra 27 localidades UF para 1092.
- Catálogo independente, não oficial: https://quantilica.com/fish/tabelas/1093/numero-informantes-quantidade-peso-total-carcacas-suinos-abatidos-mes-trimestre-tipo-inspecao — mostra 26 localidades UF para 1093.
- Catálogo independente, não oficial: https://quantilica.com/fish/tabelas/1094/numero-informantes-quantidade-peso-total-carcacas-frangos-abatidos-mes-trimestre-tipo-inspecao — mostra 26 localidades UF para 1094.
- Não foi identificada oficialmente a UF ausente em 1093 e 1094, nem sua cobertura ao longo do histórico. Não interpretar ausência como zero ou tratar contagem do catálogo como lista homologada.

### Correção executada
- Auditar por 27 UFs invariáveis era incorreto. O algoritmo de auditoria BR x UF agora exige contrato explícito por competência com especie, tabela, lista nominal de UFs, fonte de evidência e SHA256 de metadados.
- Sem cobertura explícita, retornar COBERTURA_NAO_VERIFICADA, sem soma e sem resíduo.
- Com lista válida, comparar apenas cobertura exatamente coincidente; nenhuma ausência ou excedente é ajustada; inconsistência retorna INCOMPLETO_SEM_IMPUTACAO ou COBERTURA_DIVERGENTE_SEM_IMPUTACAO.
- Cobertura declarada pode ser diferente a cada competência; comparação não garante homologação, que permanece falsa. As fixtures 25/26/27 UFs são artificiais, sem supor qual UF real faltaria.

### Bloqueio técnico
- Tentativas diretas de acessar os serviços oficiais servicodados.ibge.gov.br/api/v3/agregados/{id}/metadados e apisidra.ibge.gov.br/values/t/1092/n1/1/p/202602/v/allxp/h/y não conseguiram recuperar JSON. O ambiente de execução local também não resolveu os hosts oficiais via DNS.
- Não foram confirmados IDs oficiais de variáveis/categorias nem a estrutura exata DnC dos resultados de API, tampouco direitos para coleta operacional. Não declarar histórico real ou previsão homologada.

**Próxima ação:** obter uma amostra oficial autêntica e permitida por espécie, validar metadados e listas de localidades por referência, executar parser, reconciliar totais e arquivar SHA e datas antes de backfill/agendamento.

## Continuidade 21/10/2026 — histórico 1997–1999 e vintages bitemporais

### Correção de alcance histórico
- O SIDRA 1092, 1093 e 1094 começa no 1º trimestre de 1997 (consultar https://sidra.ibge.gov.br/pesquisa/abate/tabelas/ ). Os parsers novos rejeitavam erroneamente anos anteriores a 2000.
- Corrigidos o formato TRIMESTRE em src/nivon/cadeias_adicionais.py e o parser em src/nivon/pecuaria_sidra_abate.py para aceitar os anos de 1997 a 1999 sem liberar períodos anteriores à origem da pesquisa.
- Testes sintéticos de 1997-T1 e 1999-T4, além de bloqueio de 1996.

### Motor novo: vintage SIDRA
- Adicionado src/nivon/pecuaria_sidra_vintages.py, consumindo APENAS snapshots do parser offline e reconstruindo a série conhecida conforme o corte temporal (publicação e coleta).
- Coleta retrospectiva realizada agora não cria conhecimento no passado: dados não entram em um corte anterior ao momento real de coleta.
- Observações de abate são mantidas por espécie, tabela, UF, competência e indicador; revisão mais recente exige data de publicação posterior, com SHA e diferenças registradas.
- Censuras explícitas do snapshot funcionam como tombstones, impedindo que valor anterior continue como atual após ser censurado. Ausência em extrato parcial não é interpretada como zero ou censura.
- Impede duplicações, mudança de valor sem nova publicação, hash inconsistente, mistura de espécies, fuso ausente, excesso de linhas e status artificial de homologação.
- A saída permanece HISTORICO_OFFLINE_VINTAGES_NAO_HOMOLOGADO, com amostra_real_homologada=false, metadados_publicacao_verificados=false e previsao_homologada=false.
- Registro de motor incluído nas frentes BOI, FRANGO e SUINO em config/motores_inteligencia.v1.json e na allowlist de src/nivon/registro_motores.py. Sem coleta, armazenamento físico, cron, deploy ou comunicação WhatsApp.

### Evidências
- Testes 100% sintéticos: tests/test_pecuaria_sidra_snapshot.py e tests/test_pecuaria_sidra_vintages.py; também permanecem os testes de qualidade territorial.
- GitHub Actions https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39593598730: 1.226 testes, zero falhas, 5 ignorados, gates compileall, validação de catálogo e registro de motores aprovados.
- A documentação da API oficial permanece em https://servicodados.ibge.gov.br/api/docs/agregados?versao=3, mas endpoints de valores e metadados 1092/1093/1094 continuam não acessíveis neste ambiente. Não transformar inferências do catálogo secundário em IDs oficiais.

### Próximas prioridades
1. Obter amostra REAL e autorizada da API v3 para cada espécie e validar IDs oficiais, unidades, classificações, cobertura territorial e datas; confrontar com SIDRA e publicações do IBGE.
2. Registrar comprovante de proveniência, modificações oficiais e revisões (vintage autêntico); somente então permitir REAL_SAMPLE_TESTED em avaliação independente.
3. Definir persistência histórica append-only a partir do contrato já testado e começar análises de ciclo bovino/aves/suínos com validação temporal. Nenhuma probabilidade ou preço sem evidência.

## Continuidade 21/10/2026 — cronologia fail-closed SIDRA

- Auditoria da branch confirmou parser SIDRA e motor bitemporal offline com CI anterior verde. A API IBGE v3 de metadados e a API de valores SIDRA não responderam no navegador de pesquisa e na rede do container (DNS): nenhum JSON real foi obtido.
- Evidência externa, NÃO HOMOLOGADA de metadados: https://quantilica.com/fish/variaveis/284 e https://quantilica.com/fish/tabelas/1092/numero-informantes-quantidade-peso-total-carcacas-bovinos-abatidos-mes-trimestre-tipo-rebanho-tipo-i indicam 284 como animais abatidos nas tabelas 1092/1093/1094, mas não autorizam preencher mapas oficiais automaticamente nem inferir unidades e categorias de extrato real.
- Vulnerabilidade corrigida em src/nivon/pecuaria_sidra_vintages.py: anteriormente observação manual com referência arbitrária ou publicação anterior ao encerramento de um trimestre poderia atravessar a seleção as-of; o motor agora exige fim de trimestre canônico, origem >= 1997, publicação posterior ao encerramento para valores e censuras.
- Validação temporal harmonizada em src/nivon/pecuaria_sidra_abate.py: a publicação precisa ser >= 00:00 UTC do dia posterior ao fim da competência. Este gate não autentica o timestamp, apenas barra um intervalo objetivamente impossível.
- Testes adversariais novos em tests/test_pecuaria_sidra_vintages.py e tests/test_pecuaria_sidra_snapshot.py: referência 2026-T2 registrada em setembro, registro de 1996, publicação em junho antes do fim do trimestre, censura antecipada e controles positivos de 1997.
- Quatro datas canônicas preservadas nos resultados ou objetos: competência, referência, publicação e coleta. Publicação/coleta são DECLARADAS por operador, ainda não comprovadas com divulgação oficial histórica; não promover vintages nem classificação para observado sem evidência.

**Pendências em ordem:** (P0) amostras autênticas API v3/values das 3 tabelas e mapeamento por documentação oficial; (P0) homologação de licença/proveniência de aquisição e publicação, comparando o período do extrato à divulgação original; (P1) reprodução real BR x UFs por cobertura efetiva e revisão; (P1) persistência append-only e backtesting PIT por espécie. Sem merge, deploy, cron, envio ou preço real.

## Continuidade 21/10/2026 — sinais especiais da API SIDRA

### Evidência técnica e correção
- A documentação CRAN do sidrar (https://cran.r-project.org/web/packages/sidrar/vignettes/Introduction_to_sidrar.html) distingue: `-` = ZERO ABSOLUTO; `X` = dado INIBIDO; `..` = NÃO APLICÁVEL; `...` = NÃO DISPONÍVEL. Não usar pacotes que convertem todos automaticamente em NA sem preservar token original.
- O antigo parser de abate confundia `-` com NA e o eliminava da série de observações; isso é erro de classificação, não apenas limitação de cobertura.
- Corrigida src/nivon/pecuaria_sidra_abate.py: `-` convertido explicitamente em zero observacional, SEM imputação; X/../... seguem sem valor e NÃO viram zero. O retorno preserva `marcadores_sidra` com símbolo e significado por UF, trimestre e indicador, sob o SHA256 do bruto.
- Compatibilidade preservada com `linhas_indisponiveis` e `pecuaria_sidra_vintages`; teste ponta a ponta prova que zero absoluto continua valor zero e X mantém censura, sempre respeitando o corte de coleta.
- Testes adicionais em tests/test_pecuaria_sidra_snapshot.py para `-`, `X`, `..`, `...`, mistura de valor zero e censura e trânsito para consulta temporal.

### Limites de evidência
- A semântica dos símbolos foi verificada com referência técnica externa CRAN, não com uma amostra autenticada das tabelas 1092/1093/1094; a homologação oficial ainda precisa de resposta real e validação por tabela.
- Nenhum coletor/cron, persistência, reclassificação editorial ou série real foi ativado. O estado dos motores continua CODE_TESTED_SYNTHETIC_ONLY.
- Próximo gate P0: capturar um response real autorizado SIDRA ou Agregados v3 para cada espécie, conferir dimensões, códigos, unidade, sinais especiais, direitos e datas de publicação; registrar hash e validar as revisões por vintage.

## Continuidade 21/10/2026 — arquivo local append-only de evidencias SIDRA

### Decisão técnica
- Documentação oficial de Agregados IBGE v3: https://servicodados.ibge.gov.br/api/docs/agregados?versao=3 distingue endpoints de metadados, periodos, localidades e valores. Esses quatro conjuntos sao provas independentes a registrar antes de homologar dados.
- Tabelas SIDRA 1092 (bovinos), 1093 (suinos) e 1094 (frangos) e abrangencia formal de inspecao constam na documentacao do IBGE: https://www.ibge.gov.br/estatisticas/economicas/servicos/9203-pesquisas-trimestrais-do-abate-de-animais.html.
- O IBGE comunicou em 05/05/2023 a revisao historica da 1094 referente a 2008-2022. Sem vintages coletados ANTES dessa revisao, nao se deve simular retrospectivamente a primeira edicao.

### Código e isolamento
- Novo src/nivon/pecuaria_sidra_arquivo.py: somente recebe bytes previamente obtidos; NAO realiza HTTP, downloads, cron, deploy ou distribuicao.
- Arquivo SQLite LOCAL selecionado pelo operador; guarda payloads binarios de valores e metadata, URLs HTTPS estritamente vinculadas ao ID de tabela, datas declaradas, SHA-256 de cada payload e status ARQUIVADO_NAO_HOMOLOGADO.
- O ID do objeto de metadados deve coincidir com a tabela no URL de metadados, na URL de valores e na especie selecionada. Um ID divergente falha fechado.
- Duas triggers SQLite impedem UPDATE e DELETE pelas operacoes normais da aplicacao; INSERT OR IGNORE com UNIQUE fornece idempotencia. Administrador com acesso ao SQLite pode modificar banco e triggers: NAO qualificar como WORM ou armazenamento criptograficamente imutavel.
- Recuperacao verifica novamente os hashes dos dois blobs e sinaliza corrompimento, mas SHA-256 e host declarado NAO comprovam origem HTTP real.
- LEITURA e ARMAZENAMENTO requerem permissoes explicitas de status_fonte. Ausencia ou status pendente bloqueiam escrita. Nao criar banco sob o repositorio publico nem inserir respostas restritas em CI.
- Testes sinteticos em tests/test_pecuaria_sidra_arquivo.py cobrem roundtrip, idempotencia, edicoes por coleta, 3 especies, triggers, alteracao maliciosa, direitos, URLs host/tabela, JSON, cronologia e limites. Dados e metadados sao MOCKS, nao capturas IBGE reais.

### Contrato de maturidade
- O arquivo nao faz prova de autenticidade de datas de publicacao nem coleta. Exibe dados_reais_verificados=false, timestamps_autenticados=false e previsao_homologada=false. O motor de vintages continua independente e nao recebe nenhum registro automaticamente.
- Para passar a amostra real: obter HTTP 200 autentico via fonte oficial, guardar URL exata, response headers e timestamp de captura auditavel fora deste componente, validar metadados, categoria TOTAL, unidade, variavel e cobertura, obter licenca/proveniencia e executar os testes reais. Gravar apenas material permitido.
- P0 ainda bloqueado: acesso a payload oficial 1092/1093/1094. P1 avancou somente no mecanismo LOCAL de armazenamento de evidencias; sem persistencia operacional, sem backfill historico e sem simulacao de vintages anteriores.

## Continuidade 21/10/2026 — unicidade e conflito de capturas

### Falha corrigida
- O arquivo SQLite anteriormente indexava (especie,tabela,url_valores,url_metadados,coleta,hash_valores,hash_metadados) e aplicava INSERT OR IGNORE. Duas capturas com mesmo instante declaradamente coletado mas diferentes hashes ou datas de publicacao podiam coexistir e causar ambiguidade ou falsa idempotencia.
- src/nivon/pecuaria_sidra_arquivo.py agora usa indice unico de identidade (especie,tabela,url_valores,url_metadados,coleta_declarada), valida previamente publicacao e ambos hashes em repeticoes, e recusa colisao divergente com DadoInvalido. Capturas de outro instante continuam podendo representar novas edicoes. Isto nao comprova autenticidade de timestamp.
- O arquivo existente criado com o esquema antigo agora é detectado via PRAGMA index_list/index_info, falhando fechado. Migracao auditada (backup, reconciliacao de chaves, verificacao de hashes, plano de rollback) e requisito explicito antes de usar banco legado; nao alterar tabelas historicas automaticamente.
- Novos testes sinteticos em tests/test_pecuaria_sidra_arquivo.py demonstram idempotencia estrita, conflito de publicacao, conflito de ambos payloads, novas coletas legitimas, indice UNIQUE e bloqueio de esquema legado.

### Pesquisa de fonte — controle de proveniencia
- Retentativas nesta rodada de GET metadados https://servicodados.ibge.gov.br/api/v3/agregados/1092/metadados e valores https://apisidra.ibge.gov.br/values/t/1092/n1/1/p/202602/v/allxp/h/y falharam na rede local com Temporary failure in name resolution; o navegador web tambem informou endpoints inacessiveis. Nao existe payload oficial verificado.
- Fontes secundarias (nao homologadas) identificam variaveis candidatas 284 (Animais abatidos) e 285 (Peso total das carcacas): https://quantilica.com/fish/variaveis/284 e https://dbfloja.com.br/ferramentas/radar-abate. Nunca aplicar esses IDs como mapeamento aprovado sem metadados oficiais da tabela, unidade e periodo.
- O arquivo local permanece sem captura oficial, sem prova de publicacao historica e sem ativacao de coleta, backfill ou previsao. IDs, categorias e layout sao pendencias P0.

**Proxima acao P0:** obter response oficial autenticavel, aferir hash, timestamps, layout DnC, categoria TOTAL, unidades e direitos por especie; entao validar normalizador contra fixture real e anotar divergencias. **Proxima acao P1:** documentar migracao controlada de banco local legado se houver material efetivamente armazenado. Sem merge/deploy/cron/custo.
