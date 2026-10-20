# NIVON — Auditoria comparativa da inteligência marítima
**Corte:** 2026-10-20. **Status:** desenvolvimento em branches; não homologado nem implantado.

## Fontes e limites da auditoria
- Legado examinado: [AgroLogMT](https://github.com/brunocapellari-dotcom/AgroLogMT), `main`; código em `models/*maritime*.py`, `models/port_call_engine.py`, `models/shipping_*.py`, `collector/ais_*.py`, `collector/official_lineup_*.py`, `collector/lineup_normalizer.py`, `collector/port_lifecycle.py`, contratos, testes e documentação.
- Destino examinado: [NIVON PR #6](https://github.com/brunocapellari-dotcom/NIVON/pull/6), branch `feat/maritime-intelligence-agrolog-20261019`, *empilhada* sobre PR #1. A `main` do NIVON não contém essa implementação.
- Este incremento: PR #15, branch `fix/maritime-event-evidence-20261020`, base PR #6. Revisão de código/contratos, não ensaio com operação real.
- Resultados de CI devem sempre ser atribuídos ao SHA testado. Código presente, testes sintéticos e dados reais homologados são **categorias distintas**.

## Matriz de reaproveitamento (AgroLog → NIVON)
| Área | Legado | NIVON PR #6 | Decisão |
| --- | --- | --- | --- |
| Qualidade e identidade AIS | `models/ais_quality.py`, `models/vessel_identity.py` | `src/nivon/maritime/ais_quality.py`, `vessel_identity.py` | REUSE, direitos e validação temporal obrigatórios |
| Geofences e port calls | `models/port_geofence.py`, `models/port_call_engine.py` | módulos homônimos migrados | REUSE + FIX de continuidade de dwell em PR #15 |
| Line-up/port calls | `collector/official_lineup_html.py`, `official_lineup_pdf.py`, `models/shipping_reconciliation.py` | `nivon.portos_automaticos`, `nivon.maritime.official_lineup_bridge`, `shipping_reconciliation.py` | Preservar parser único; FIX de porto/escala/duplicatas em PR #15 |
| AISStream | `collector/ais_stream.py`, `ais_stream_client.py` | adaptadores equivalentes + `AISStreamRights` | REUSE condicional; sem AIS gratuito presumido |
| ETA, filas, alertas e anomalias | `models/maritime_eta.py`, `maritime_queue.py`, `maritime_queue_forecast.py`, alerting/anomaly | correspondentes sob `nivon.maritime` + `model_validation.py` | REUSE em SHADOW; previsão não calibrada |
| Fonte/histórico | coletores e `models/maritime_source_health.py` | `maritime_store.py`, `antaq_archive.py`, source health | ADAPT; histórico estatístico não confirma automaticamente escala individual |
| Interface | `maritime_ui` | `maritime_ui` + `maritime_gateway.py` local read-only | REUSE para testes locais; bloquear rede externa |
| Integrações agro/logística | `models/maritime_trade_flow.py`, weather e integração AgroLog | `cross_domain.py`, `intelligence.py` e motores migrados | ADAPT contratos compartilhados; não prometer causalidade |
| Aceite final | `contracts/maritime_final_acceptance.v1.json` | contrato correspondente e release gate | Manter fail-closed até E2E real |

## Achados críticos desta revisão
1. **P0 — AIS dwell não contíguo:** o legado e a migração selecionavam todas as observações de uma zona antes de calcular a permanência; saída para outra zona e retorno, ou blackout, podiam ser tratados como permanência ininterrupta. PR #15 segmenta sequências e impõe intervalo máximo conservador de 60 minutos entre mensagens. **Esse limiar ainda requer calibração por porto, cobertura e fonte.**
2. **P0 — evidência de porto errado:** a reconciliação por IMO/MMSI podia marcar match mesmo quando a posição tinha `port_id` de outro porto. PR #15 preserva AIS de mar aberto sem porto atribuído e exige porto compatível para AIS geolocalizado.
3. **P0 — operação oficial associada à escala errada:** em chamadas diretas, um `PortOperation` com identificador coincidente mas porto divergente podia promover uma escala a `COMPLETED_REALIZED`. PR #15 obriga validar `call_id`, porto e `source_id`.
4. **P0 — duplicação por linha:** duas linhas de programação com o mesmo `call_id` eram contabilizadas como duas escalas, e operações repetidas eram silenciosamente sobrescritas. PR #15 falha de modo seguro; a modelagem correta é escala 1:N linhas de mercadoria/terminal/operador, com totalizadores por `COUNT DISTINCT` da escala.
5. **P0 — documentação e direitos:** proveniência de código entre repositórios deve ser preservada; permissões de AIS, geofences/cartas, programação portuária, retenção e redistribuição são independentes.
6. **P0 — falta de evidência operacional:** testes sintéticos não substituem documentos oficiais, snapshots históricos, posicionamentos AIS licenciados e validação externa.

## Contratos indispensáveis
- Identidade principal: `port_call_id` canônico vinculado a `port_id` e DUV/ID oficial quando presente; `IMO` é identidade de embarcação, não de escala. Não fundir escalas distintas só porque o navio é igual.
- Dimensão 1:N: uma escala pode ter múltiplos registros por mercadoria, terminal, operador e sentido; preservar as linhas, agregar sem duplicar escalas.
- Quatro datas: `competencia`, `data_referencia`, `data_publicacao`, `data_coleta`; mais `event_time` da ocorrência quando houver. Sem publicação comprovada, proibir retrospectiva *as-of* baseada na linha.
- Classes separadas: `PROGRAMMED_LINEUP` (programação); `AIS_OBSERVED` (posição); `DECLARED` (declaração); `INFERRED/ESTIMATED` (modelo); `OFFICIAL_OPERATION_OBSERVED` (evento/volume confirmado conforme fonte).
- Distinção explícita `planned_volume_t` vs. `realized_volume_t`, e `ETA` vs. `ATA/ATB/ATD`; não preencher null com zero nem imputar horário de ETA a partir de data.
- Nenhuma estimativa ou AIS isolado promove movimentação física realizada. Relatórios precisam citar fonte, snapshot SHA, âmbito, timestamp e direitos.

## Backlog priorizado após PR #15
### P0 — antes de qualquer release
- [ ] Revisão independente da PR #6 e desta PR #15, incluindo supply chain, segurança de UI/API e licença de dependências.
- [ ] Reconciliar o contrato de `OfficialPortSignal` à identidade explícita de `port_id` + `call_id`, impedindo mistura de sinais em reutilizações diretas do reconstrutor.
- [ ] Homologar no mínimo três edições verdadeiras por fonte piloto (Santos, Paranaguá, Santarém, Vila do Conde e Itaqui), com arquivo original, hash, granularidade, versão, fuso, DUV/IMO e quatro datas.
- [ ] Certificar direitos por operação AIS (captura, retenção histórica, inferência, visualização, API, redistribuição comercial); confirmar limites técnicos e orçamento.
- [ ] Validar deduplicação escala × mercadoria, revisão de ETA e múltiplas visitas do mesmo IMO.
- [ ] Integrar versão de line-up ao armazenamento e testar replay sem vazamento de publicação futura; consistência de cortes temporais.
- [ ] Validar CI no SHA consolidado final e aceite humano de segurança/qualidade. Sem merge nem deploy implícito.

### P1 — inteligência quantitativa e integração
- [ ] Backfill histórico ANTAQ autorizado com validação de `Atracacao/Carga/Mercadoria` e revisões; jamais imputar operação individual a partir de agregado mensal.
- [ ] Calibrar janela, lacunas, geofence e estados AIS para cada porto com verdade observada; medir falsos positivos/negativos e cobertura.
- [ ] Treinar e comparar ETA e filas com baselines, folds walk-forward, janelas as-of, intervalos e calibração; publicar probabilidades só com histórico suficiente.
- [ ] Desenvolver Vessel Queue Index e Port Pressure Score com universo, capacidade, cobertura AIS, missingness, pesos versionados e incerteza explícitos.
- [ ] Integrar meteorologia, hidrologia e corredores terrestres por chaves espaciais/temporais rastreáveis.

### P2 — escala e internacionalização
- [ ] Ampliar parsers, sem duplicação de coletores, para outros portos brasileiros com disponibilidade e direitos aprovados.
- [ ] Cobertura internacional priorizada por fertilizantes, soja, milho, farelo, petróleo e seus corredores.
- [ ] Gateway autenticado, observabilidade, operação contínua, backup criptografado/restauração, reconciliação diária e teste operacional de 7 dias — somente após gates.

## Verificação desta PR
- Testes novos: `tests/test_maritime_event_integrity.py`, 12 cenários sintéticos, incluindo mistura de MMSIs.
- Comandos: `PYTHONPATH=src python -m unittest discover -s tests -v`; `cd maritime_ui && npm ci --ignore-scripts && npm run build`.
- Resultado CI para SHA de código e testes `3be4e42c4a4a207ff5b7e523e67748d574dd2f23`: workflow Python [39482547228](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39482547228) aprovado (1019 testes, 5 ignorados); build marítimo [39482547193](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39482547193) aprovado.
- **Nota:** esta atualização de documentação não altera código nem testes; as CIs citadas cobrem o último SHA de código. Uma futura alteração funcional exige CI no novo SHA antes de merge.

**STATUS OPERACIONAL:** CODE_TESTED_SYNTHETIC_ONLY / RELEASE_BLOCKED / NO_DEPLOY.
