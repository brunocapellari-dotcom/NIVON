# NIVON — Primeira auditoria de logística terrestre e combustíveis (20/10/2026)

## Base de comparação e integração

- `NIVON/main`: somente README; não é aplicação operacional.
- Branch de referência: `feat/motor-tendencias-transversal-20261020`, PR #12 (draft); esta mudança é EMPILHADA sobre seu HEAD congelado, não em `main`.
- Legado: `AgroLogMT/models/logistics_corridors.py`, `contracts/logistics_corridor.v1.schema.json`, `gateway/freight_ingest.py`, `models/logistics_gis_benchmark.py`. Reutilizar conceitos mediante revisão, não copiar agregações heterogêneas.
- Diesel NIVON: `anp_diesel.py` (CSV e semana calendário **inferida**), `anp_diesel_store.py` (vintages offline), `anp_ppi.py` (PPI estimada, diferente de revenda); ANP LPC semanal em branch editorial #8 precisa reconciliação separada.
- ANTT: `antt_ferrovia.py` e `antt_ferrovia_csv.py` são fluxos ferroviários TU/TKU, nunca MDF-e rodoviário.

## Risco crítico corrigido nesta PR

O motor de ofertas da PR #12 calculava uma mediana diária de preços de **lotes de diferentes estabelecimentos** identificados apenas por origem municipal e destino. Tal estimativa não poderia servir de referência de frete por município e violava o contrato comercial definido. Agora a tendência exige:
`pickup_entity_id`, `transportadora_id`, `descarga_entity_id` e `regime` além de origem/destino, produto, veículo, pedágio e lotes resolvidos.
O resultado permanece *observado histórico*, não previsão. Não emitir probabilidades calibradas sem dados e backtesting as-of.

Novo módulo `fretes_registros.py` preserva separadamente cada registro anunciado com base, pedágio, cheio, características e proveniência. Republicações dependem de uma `oferta_id` canônica resolvida; alterações de preço são preservadas como eventos diferentes. Indicadores por município se limitam a CONTAGENS de estabelecimentos, transportadoras e publicações com exibição explícita dos IDs; nenhum preço municipal médio, mediano ou representativo é produzido.

`distancia_e_custo` oferece R$/TKU derivado apenas com distância rodoviária verificada; R$/km por veículo exige carga efetiva informada, e é receita hipotética derivada de anúncio, **não custo real operacional**.

## Matriz de lacunas e bloqueios

| Prioridade | Componente | Estado verificado em código | Próxima ação e aceite |
| --- | --- | --- | --- |
| P0 | Fretes WhatsApp / identidade | legado tem ingestão, NIVON tendências heterogêneas corrigidas nesta branch | integrar prova de `pickup_entity_id` e transportadora com origem da mensagem, resolver aliases auditáveis, conferir com casos reais e direitos |
| P0 | Diesel semanal ANP | parser mensal e store offline; semanal oficial em PR #8 | reconciliar ramos, testar >=3 edições XLSX reais com publicação e cobertura, determinar direitos/horário, habilitar somente após homologação |
| P0 | Histórico e vintages | código parcial offline | armazenar RAW autorizados fora do Git, SHA-256, publicação, coleta, referência, competência, backfill e revisões |
| P1 | Distâncias, pedágios, rotas | contrato AgroLog e benchmark GIS | integrar SNV/DNIT e concessões ANTT; avaliar OSM/OSRM com licenças e benchmark, roteamento operacional OFF |
| P1 | Fluxos ferroviários | parser ANTT existe | reconciliar códigos de estação, concessão, fonte, unidade TU/TKU e calendário; teste com XLSX real |
| P1 | Pressão de safra | não demonstrado E2E | linkar produção CONAB/IBGE, demanda portuária, chuva e disponibilidade de rota apenas com dados e indicadores comparáveis |
| P1 | Tendência/probabilidades | PR #12 gera tendência histórica sem skill real | treino separado por corredor/estabelecimento/condições, walk-forward, calibração, intervalos e abstenção |
| P2 | Diesel internacional | PPI existe, câmbio/ANP fontes parciais | integrar preço produtor/importação, ANP PPI, PTAX, defasagens, tributos e direitos; não confundir revenda e paridade |

## Corredores-alvo, sem distâncias ou fretes inventados

Sorriso–Rondonópolis; Sorriso–Dom Aquino; Sinop–Miritituba/Itaituba; Santos/Guarujá; Paranaguá; Uberaba/Araguari; demais rotas nacionalmente relevantes após confirmação de estabelecimentos e destinos. **Miritituba é terminal/localidade em Itaituba/PA, não código municipal próprio.** Não somar fluxos de destino distintos sem reconciliação do terminal e sentido.

## Status de execução

Código/testes sintéticos são somente provas de regras. Não houve coleta/armazenamento de dados reais, contato com WhatsApp, ativação de scheduler, serviço externo, recurso OCI, cobrança, deploy, merge ou autorização de previsão. Exigir CI no SHA final e revisão crítica antes de incorporação na PR de integração #13.

## Evidência externa de fontes oficiais verificada em 20/10/2026

- ANP, últimas semanas: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas — semana 11–17/10/2026 publicada na página; manter hora de publicação da **edição baixada**, não a data de alteração genérica da página.
- ANP, séries semanais consolidadas desde 2013: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/ — separar séries de Brasil, UF e município, sem confundir médias **ANP de DIESEL** com média de **FRETES de anúncios**; o veto de média municipal vale a preços de FRETES anunciados, não ao indicador público de diesel por município.
- ANTT, produção origem/destino ferroviário 2026 (licença CC BY): https://dados.antt.gov.br/pt_BR/dataset/sistema-de-acompanhamento-do-desempenho-operacional-das-concessionarias-siade/resource/c2854ec9-1cc5-4554-a1ae-96c5f37b5df6 — colunas Mes_Ano, Ferrovia, Mercadoria_ANTT, Estacao_Origem, Estacao_Destino, TU, TKU. Metadados atualizados em 02/10/2026; **estação não equivale a município**.
- ANTT, praças de pedágio: https://dados.antt.gov.br/pt_BR/dataset/praca-de-pedagio/resource/9aa29243-c54c-4084-bc3d-c44a75c9bd7e — cadastro não é tarifa por categoria de veículo nem comprova trajeto percorrido; exigir tabela tarifária datada e percurso verificado.
- DNIT, PNV/SNV https://www.gov.br/dnit/pt-br/assuntos/atlas-e-mapas/pnv-e-snv — base de malha viária, **não** distância comercial porta-a-porta sem roteador/topologia validada.

## Sensibilidade do diesel implementada (offline)

`diesel_pressao.py` gera cenário matemático **hipotético**: litros = distância operacional validada × consumo específico informado; custo combustível por t = litros × preço diesel por litro / carga informada. Diferença de custo por t NÃO implica repasse ao frete anunciado/contratado. Proíbe mistura DIESEL/DIESEL S10, ausência de evidência, número não finito e premissa fora de faixa. O preço ANP de revenda é amostral, não custo observado do transportador. Testes em `tests/test_diesel_pressao.py`.

**Gates preservados:** não há coleta automática de combustível, integração operacional da ANP semanal, custo real de frota, pagamento de pedágio ou volume observado a partir destes módulos.


## Continuidade 20/10/2026 — ponte E2E offline entre WhatsApp AI e NIVON

Auditoria efetiva dos contratos:
- `WHATSAPP_AI/app/models.py` e `app/pipeline.py`: o evento possui `event_id/version/tenant_id/classification/source_event_ids/rate/rate_unit/entities/provenance`. `loading_point` e `company` podem ter `canonical_id=None`; o pipeline permite evento sem estabelecimento, pedágio, equipamento e regime. A existência de evento na outbox **não comprova** que ele seja comparável comercialmente.
- `AgroLogMT/gateway/freight_ingest.py`: aceita eventos canônicos com `entities` e `raw_reference`, mas sua classe `FREIGHT_OFFER` não exige pickup canônico; ingestão não homologa a observação para análise do NIVON.
- `AgroLogMT/collector/freight_observations.py`: cluster por município/destino/produto/preço/dia não deve ser usado como prova de mesmo embarque/transportadora; não pode governar deduplicação comercial do NIVON.
- A PR #30 criou uma análise de variação pareada e gates R01 (painel constante). **Integrar a lógica dessa PR com esta branch, sem sobrescrever os mesmos arquivos arbitrariamente.**

Novo `src/nivon/fretes_adapter_whatsapp.py` implementa uma ponte 100% offline:
1. Consome envelope compatível com `FreightEvent` do WhatsApp AI, somente `FREIGHT_OFFER` ou `UPDATE` economicamente comprovado. Rejeita `CANCELLATION`, `FREIGHT_REQUEST`, inferido, unidade misturada, evento futuro, data sem timezone ou valor ambíguo.
2. EXIGE resolução canônica externa vinculada a **tenant + event_id + version + source_event_id** com SHA-256 de evidência e correspondência de origem IBGE, destino IBGE, pickup, transportadora, descarga, equipamento, produto, regime PF/PJ e natureza do preço `BASE`. Se entidades já contiverem `canonical_id`, divergência é bloqueante.
3. EXIGE atestação autorizada com identificador de fonte, provider, tenant, SHA-256 de evidência e operações `LEITURA`, `ARMAZENAMENTO` e `ANALISE`. O coletor **não pode fabricar atestação a partir do próprio conteúdo da mensagem**.
4. Diferencia pedágio adicional com valor verificado do caso `NAO_INFORMADO`. Desconhecido não vira zero, `frete_cheio` fica nulo. Impede tratar valor cheio como base por conveniência.
5. Gera IDs pseudonimizados HMAC-SHA256 com chave de runtime e isolamento de tenants para publicação, registro (event_id+versão) e oferta econômica. Não retorna texto bruto, contato, número de WhatsApp ou referências RAW.
6. Envia `OfertaFrete` ao registro já existente, preservando evolução de preços em vez de colapsar reajustes em repostagens. **Não** consulta nem publica dados reais.

O contrato da atestação é candidato para futura interface entre projetos, não prova que uma assinatura, autorização externa ou resolução operacional esteja implantada. O SHA citado garante referência a um artefato declarado, **não verifica automaticamente sua autenticidade**. Antes de uso real, o emissor confiável deve conferir RAW com acesso autorizado, política/assinatura do registro de direitos, origem dos identificadores canônicos, anti-replay, sigilo da chave HMAC e revogação. Teste de integração de rede/WhatsApp permanece bloqueado.

**Teste sintético isolado**: `PYTHONPATH=src python -m unittest tests.test_fretes_adapter_whatsapp -v`; suíte total em `.github/workflows/testes.yml` deve aprovar no SHA final.

### Pendências reordenadas após PR #30

- **P0**: conciliar adaptador/contratos de propriedade de origem com WhatsApp AI/AgroLog; carregar eventos reais somente sob licença e escopo comprovados; testar revogação e reprocessamento.
- **P0**: integrar PR #30 (variação pareada) sem recuperar análise por mediana de anúncios misturados e sem conflito com PR #18. Confirmar CI e auditoria independente.
- **P0**: conciliar ANP semanal da PR #8 com `anp_diesel_store` da PR #12, 3 arquivos históricos reais, edição/as-of e licenças.
- **P1**: auditar distâncias DNIT e pedágios por equipamento/categoria, condições PF/PJ e sentido; instrumentar custos de frota apenas com premissas documentadas.


## Continuidade 20/10/2026 — histórico bitemporal ANP semanal oficial

A PR #8 implementou dois parsers candidatos distintos: `anp_resumo_lpc.py` para o RESUMO SEMANAL LPC com aba MUNICIPIOS (fonte `ANP_RESUMO_LPC_SEMANAL`) e `anp_semanal_municipios.py` para o arquivo anual semanal com layout informado. Nenhum deles comprovou ainda três XLSX reais e datas de publicação originais. O `anp_diesel_store.py` da PR #12 **NÃO pode receber diretamente essas séries** porque seu contrato exige `semana_inicio_inferida` e mediana/mínimo/máximo do CSV mensal, enquanto LPC semanal contém a média e a semana oficial. Converter uma na outra fabrica dados.

Novo `anp_semanal_store.py` é **store SQLite sem abertura de banco externo ou I/O de rede**. Recebe precisamente o resultado de `ler_resumo_semanal_lpc` com arquivo SHA, URL ANP original, `data_publicacao` e prova externa de publicação separada; mantém tabelas distintas para edições, capturas e médias municipais amostrais por semana oficial. Não armazena postos individuais, não insere linha ausente como zero e não mistura DIESEL e DIESEL S10. Serialização numérica é Decimal textual.

O histórico permite idempotência por hash original e múltiplas capturas da mesma edição. Para leitura `as_of`, uma edição só aparece se **data de publicação, primeira captura histórica conhecida e semana oficial** eram anteriores ao corte. Reedições da mesma semana com preços/postos divergentes bloqueiam seleção silenciosa; dado antigo é marcado vencido. A consulta devolve `publicavel=false` em qualquer situação, inclusive quando a fonte foi classificada REAL_AUTORIZADO para armazenamento. Direitos de redistribuição do indicador devem passar em gate posterior, diferente do direito de gravar. A fonte real ainda exige atestação e **não** foi ingerida.

Os campos `prova_publicacao_sha` e `prova_direitos_sha` são referências a evidências externas a verificar por agente independente; nenhum hash por si só prova autorização ou a data real da edição. O módulo não infere retroativamente uma publicação a partir de data da coleta.

Testes: `tests/test_anp_semanal_store.py` (PIT, idempotência, versões, conflito, datas futuras, permissões, preço, produtos, município e semântica); a execução GitHub Actions no HEAD final deve ser verificada.

**Gatilhos restantes P0:** merge coordenado da PR #8 sem perder `anp_resumo_lpc.py`; leitura de 3 arquivos XLSX oficiais homologados, comprovação de publicação de cada edição, licença para coleta/armazenamento e eventual publicação comercial, storage durável protegido/backup+restore, monitoramento de disponibilização e revisão de dados, reconciliação de datas as-of com o calendário oficial, integração ao briefing somente depois de homologação. Não inferir preço de abastecimento contratado ou repasse à tarifa de frete.


## Rodada de segurança e compatibilidade — 21/10/2026

### Prioridade P0: confiança dos atestadores

A auditoria demonstrou que `fretes_adapter_whatsapp.py` exigia `status=VERIFICADA`, `status=APROVADA` e SHA documental, mas qualquer chamador poderia fabricar esses campos. Foi criado `fretes_atestacoes.py` com dois domínios HMAC-SHA256 autenticados e independentes: `DIREITOS` (autorização de leitura, armazenamento e análise) e `RESOLUCAO` (identidade do ponto de embarque e transportadora). A assinatura cobre o JSON inteiro da atestação, incluindo emissor, versão, validade, fonte, permissões e prova declarada. A resolução também exige SHA-256 de todo o envelope `FreightEvent`, vinculando-a à exata versão e conteúdo, não apenas ao ID. Rejeita emissor ou chave incorretos, prazo vencido/futuro, falhas de integridade e assinatura ausente; a chave HMAC de pseudonimização de IDs não pode ser reutilizada para atestações. Cinco testes adversariais adicionais cobrem adulteração, expiração, assinaturas ausentes e isolamento de chaves.

**Limitações de segurança:** HMAC implementado **não** é uma autoridade operacional por si só. O runtime futuro precisa prover chaves exclusivas, emitentes aprovados, relógio/recebimento confiáveis, revogação e rotação, auditoria de validação do RAW, isolamento por tenant e evidência de consentimento/licença. Nenhuma credencial de produção foi criada, exibida ou armazenada em GitHub. A integração permanece OFFLINE e não pode assumir que qualquer dicionário arbitrário seja um atestador confiável.

### Prioridade P0: contrato para motor de tendências pareadas

A PR #30 já implementa a estatística de variações pareadas `pickup_entity_id + transportadora_id` e corrige o viés de mudanças na composição de estabelecimentos. **Não duplicamos o cálculo.** A PR #18 acrescenta o preparador `fretes_painel_pr30.py` para disponibilizar registros `OfertaFrete` em formato compatível com os campos exigidos pelo motor da PR #30, mantendo invariantes mais estritos de `descarga_entity_id`, `regime`, `equipamento`, `produto`, `pedagio` e rota municipal. Não cruza condições econômicas nem permite preço diferente do mesmo ponto+transportadora no mesmo dia. Descarta repetições sem preço divergente como unidade estatística independente, **sem apagar os anúncios individuais na base**. Avalia o `as_of` por timestamp de publicação/coleta, evitando reoferta futura vazando para uma sessão histórica. Envia apenas `frete_base_brl_t`, não confunde preço cheio com base e não atribui média municipal. `edicao_sha256` é explicitamente hash **DERIVADO de normalização**, não prova do arquivo RAW. Até a integração, a saída é `PREPARADO_OFFLINE_NAO_HOMOLOGADO`, `publicavel=false`.

A PR #30 continua draft e não é ancestral da PR #18. O contrato de preparação poderá ser integrado **após a reconciliação coordenada** do arquivo `tendencias_mercados.py`, evitando substituição da implementação pareada por uma versão legada. Tests `tests/test_fretes_painel_pr30.py` verificam base, duplicatas, pares, condições comerciais, valores conflitantes, cortes intradiários e classificação sem publicação. Nenhuma previsão probabilística real foi criada.

### Gates de continuidade

1. **P0 — integrar código e testes:** reconciliar PR #18 com PR #30 preservando invariantes de descarga, regime, base/pedágio, corte intradiário e identidade; executar regressão cruzada no SHA resultante.
2. **P0 — trust chain real:** verificar atestações assinadas por resolvers autorizados e dados RAW em ambiente confiável, incluindo revogação/rotação; nenhuma entrada comercial sem prova.
3. **P0 — ANP semanal:** conciliar parser PR #8 ao store oficial criado na PR #18; obter legalmente e conferir ao menos três XLSX reais e respectivos horários de publicação/vintages.
4. **P1 — corredores:** introduzir itinerários validados DNIT/SNV, pedágios por categoria, sentidos e classes de veículos antes de comparar R$/TKU ou custos.
5. **P1 — previsão:** somente depois de volume histórico suficiente, calibração temporal por corredor e métricas de generalização robustas.

Nenhum merge, deploy, coleta de rede, envio de WhatsApp, custo ou integração de fonte paga. Código aprovado por fixtures/CI não representa operação real.


## Continuidade 21/10/2026 — reconciliação FUNCIONAL R01 (#18 × #30) e vintage comercial

**Estado GitHub verificado antes da implementação:** PR #18 em HEAD `4b857f04316bda19fe2c5088dd10d2db1a030b1b`, PR #30 em `53544dc65317535e8c0ba6fdf238fd8539d468ac`; ambas são draft sem merge. Foram lidos `tendencias_mercados.py` e `tests/test_tendencias_mercados.py` da PR #30, SHA de blob `139d6adbe7c307973228d597af6307829cf75fe7` e `6371e76792efa53b1500fd0474ac3b45ad19ccff`.

**Port controlado para branch logística**, sem sobrescrever os arquivos compartilhados de outra frente:
- `src/nivon/fretes_tendencia_pareada.py`: metodologia R01 da PR #30 para **variações pareadas**, com identidade `pickup_entity_id + transportadora_id` estável em todos os dias e mínimo de pares. Acrescenta descarregamento e regime PF/PJ obrigatórios e constantes; valida produto, veículo, pedágio, natureza anunciada, unidade, edição, datas e ausência de mistura. Preço base não é mediana nem média municipal; somente as **variações pareadas** são resumidas para classificação descritiva. `publicavel=false`.
- `tests/test_fretes_tendencia_pareada.py`: regressões portadas da PR #30, incluindo efeitos de composição de estabelecimentos (R01), limiar relativo inadequado, dedup de anúncios e integridade das identidades, além de descarga/PF/PJ.
- `src/nivon/fretes_integracao_r01.py` liga o contrato `OfertaFrete` a `fretes_painel_pr30.py` e ao motor R01. O recorte temporal é validado até hora/minuto com timezone; a estatística recebe datas locais de MT, evitando falso `lookahead` na virada UTC. O retorno marca explicitamente a análise como **não homologada**, não previsão, sem direito de publicação.
- `fretes_painel_pr30.py`: rejeita alterações de pedágio no mesmo ponto/transportadora/dia, mesmo se o preço base for igual; mantém evidência das republicações no SHA de agregação derivado. Bloqueia referência comercial antiga divergente da data de publicação, nunca eleva uma oferta antiga ao status de atual por ter sido reencaminhada. Converte Decimal textual em número do motor apenas se houver round-trip sem perda de precisão, ou falha fechado.
- `tests/test_fretes_integracao_r01.py`: testes offline integrados cobrindo alta, baixa, estabilidade, participantes rotativos, painel insuficiente, preço conflitante, pedágio, PF/PJ, estabelecimento de descarga, produto, equipamento, limite de `as_of` intradiário e fuso de Mato Grosso.

**P0 identificado em auditoria adicional:** só comparar a data de referência com o recebimento não basta: anúncio de 2024 republicado em 2026 pode ter timestamp de WhatsApp de 2026. O `fretes_adapter_whatsapp.py` agora EXIGE que a RESOLUÇÃO assinada ateste `atualidade_comercial=VERIFICADA_NO_CONTEUDO_ORIGINAL` e `data_referencia_comercial` igual à data local da publicação. Se a evidência comercial aponta para outra edição/dia ou não foi verificada no RAW, rejeita. A atestação externa é parte do contrato; o NIVON **não** infere atualidade lendo a data do WhatsApp. Isso mantém entradas antigas para revisão fora da série atual, sem prometer detecção perfeita quando a fonte é enganosa e sem fonte de verdade.

**IMPORTANTE — reconciliação NÃO é merge/release:** o método pareado continua no arquivo compartilhado `tendencias_mercados.py` da PR #30 e, na branch de logística, está portado para módulo isolado. Antes de promover integrar ambas as árvores, consolidar **um** motor pareado canônico, remover duplicações, preservar os testes das duas frentes, validar os contratos de chamada, evitar conflito de nomenclatura e executar regressões no SHA combinado. Não executar merge automático das PRs draft divergentes.

**Ainda pendente (critério de go-live):** licenciamento real, três XLSX ANP verificados, provedor WhatsApp autorizado, resolvedor de identidade comercial e direitos com assinatura/rotação/revogação/anti-replay, trilha de evidências originais fora do GitHub, testes em dados reais autorizados, backtest point-in-time e distâncias/pedágios reais por corredor. Nenhuma coleta, deploy, envio ou contratação nesta rodada.
