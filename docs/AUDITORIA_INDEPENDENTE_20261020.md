# NIVON — Auditoria técnica independente (2026-10-20)

**Escopo imutável auditado:** integração `9f1a5e0ded09ac2246cc83b764ddb60f44436986`, PR #13.  
**Auditoria:** branch `audit/independente-gates-20261020`, exclusiva para testes e pareceres.  
**Estado operacional:** **NÃO HOMOLOGADO / GO-LIVE BLOQUEADO**.  
**Ambiente:** GitHub (metadados, árvore, fonte e jobs CI); nenhum acesso a Oracle, banco real, WhatsApp/Meta, APIs com licenças pendentes, dados privados ou produção.

## 1. Evidências verificadas

- `main` (SHA `493fe1472915e1a02210e6575126d8ea5b4e9c2e`) contém README e declara expressamente não homologação.
- PR #1 e #13 permanecem draft e sem merge; #13 contém base de integração, **não** toda a consolidação das branches #3/#6/#7/#8/#9/#10/#11/#12.
- A workflow GitHub Actions `Testes locais NIVON`, run `39480564826`, contém um job `validar-nucleo` concluído com sucesso e cinco jobs de diagnóstico com status `skipped`.
- O job verde usa `unittest` e fixtures sintéticas; não demonstra recursos cloud, coleta real, entrega, direitos de redistribuição nem modelos calibrados.

## 2. Escala de classificação

| Estado | Critério de evidência |
|---|---|
| APROVADO | Contrato definido, implementação inspecionada, testes reproduzíveis independentes passando no SHA final e E2E real aplicável com evidências e licenças |
| APROVADO_COM_RESSALVAS | Subconjunto delimitado e testado passa, mas não pode declarar operação, publicação nem previsões homologadas |
| REPROVADO | Violação reproduzível de requisito ou gate crítico, ou impedimento objetivo para a finalidade avaliada |
| NAO_VERIFICADO | Evidência ausente, ambiente inacessível ou teste não executado; não equivale a reprovação funcional |

É proibido promover resultados sintéticos a operação real. CI verde em SHA intermediário não homologa SHA final.

## 3. Severidade e política de saída

- **P0 / BLOQUEANTE:** vazamento temporal, dado inventado ou desatualizado como atual, quebra de direitos, segredo exposto, SSRF/RCE, perda de dados, acesso indevido, valores/unidades economicamente incorretos, probabilidades falsas, publicação não consentida.
- **P1 / ALTA:** inconsistência reproduzível em integração/contrato, ausência de recuperação, testes OOS insuficientes ou falhas severas de observabilidade.
- **P2 / MÉDIA:** cobertura parcial, fragilidade de manutenção, lacunas documentais que não degradam o caminho crítico.
- **P3 / BAIXA:** estilo, legibilidade e melhorias não bloqueantes.

**Gate operacional:** zero P0 e P1 abertos nos fluxos críticos; CI e evidências de execução real no SHA candidato; licenças por operação; fontes com snapshot e QC; deploy seguro; autenticação/autorização; backup e restauração testada; métricas/logs; rollback; E2E rastreável entre fonte, RAW, normalização, indicadores, briefing e envio autorizado. Sem evidência, permanece NAO_VERIFICADO.

**Gate preditivo:** versões point-in-time (publicação/disponibilidade/coleta), baseline robusto, rolling-origin temporal com períodos de embargo adequados, nenhum leakage, métricas fora da amostra por horizonte/regime, calibração e cobertura de intervalos, drift, histórico imutável de previsões. Sem isso, qualquer tendência é descritiva ou simulação não publicável como probabilidade.

## 4. Não conformidades P0 em investigação — briefing de fretes

### NC-AUD-001 — Frete com referência futura
Em `src/nivon/briefing_composto.py`, `montar_briefing` exige timestamp com fuso, mas não verifica `referencia <= data` para fretes, diferentemente dos indicadores. Teste adversarial: `test_p0_rejeita_frete_com_referencia_futura`.

### NC-AUD-002 — Frete histórico indevidamente atual
A rotina inclui anúncio de 2024 em edição de 2026 sem política de validade. Teste: `test_p0_rejeita_frete_de_2024_em_briefing_de_2026`. É preciso distinguir arquivo histórico de quadro corrente. O prazo de validade do frete deve ser configurável e sustentado por regra de negócio.

### NC-AUD-003 — Registro de frete sem identidade comercial
A rotina não exige `pickup_entity_id` nem `transportadora`. Município é agrupamento, não identidade comercial. Teste: `test_p0_rejeita_frete_sem_identidade_de_estabelecimento_e_transportadora`. A correção deve manter também produto, destino/local de descarga, equipamento, pedágio e regime quando aplicáveis, sem calcular média por município.

### NC-AUD-004 — Fonte sem direito explícito de leitura
Para fretes, `montar_briefing` só exige `PUBLICACAO_DERIVADA`, enquanto indicadores exigem também `LEITURA`. Teste: `test_p0_exige_direito_de_leitura_alem_de_publicacao`.

**Política de red/green:** os testes acima foram escritos para reproduzir falhas na implementação base; status esperado inicialmente = falha de regressão, não homologação. Correção deve ocorrer em branch de implementação, seguida por reteste independente. Caso-controle válido precisa permanecer verde.

## 4.1. NC-AUD-005 — Proteção da branch principal (P1)

Consulta direta a `GET /repos/brunocapellari-dotcom/NIVON/branches/main` em 20/10/2026 retornou `protected: false`, `protection.enabled: false`, e `required_status_checks.enforcement_level: off`; `GET /repos/.../rulesets?includes_parents=true` retornou lista vazia. Portanto, não há barreira configurada de GitHub comprovada contra merge direto sem validação/CI. **Risco de governança P1 e impeditivo para liberar release**, mesmo quando os testes passarem. Recomendação: revisar e habilitar branch protection ou ruleset efetivo com PR review independente e checks obrigatórios; esta auditoria não altera configurações administrativas.

## 5. Plano de testes por frente

| Frente | Próximo teste verificável |
|---|---|
| 01 Direção e integração | Diff e reconciliação de SHAs, IDs, conflitos e suíte no SHA consolidado |
| 02 Coletores e dados | RAW/hash, quatro datas, licenças, replay/idempotência, HTTP e payloads hostis |
| 03 Commodities | Unidades CBOT/ICE, vencimentos, timezone, fechamento/ajuste e direitos |
| 04 Agricultura | Safra x ano civil, conservação, produtividade, área e revisão de séries |
| 05 Pecuária | Balanços biológicos, unidade animal, conversão de carcaça e fontes |
| 06 Meteo/Hidro | FAO-56, NSE/KGE/CRPS, unidades, estação/malha, vintages e extremos |
| 07 Quantitativo | Walk-forward, leakage, benchmarks, probabilidades/calibração e estabilidade |
| 08 Logística | Estabelecimento/transportadora, fretes anunciados, composição e diesel |
| 09 Marítima | DUV/escala, AIS, port calls, ETA OOS, line-up x realizado e licença |
| 10 IVO | Authz por ferramenta, prompt injection, RAG com fonte, isolamento e trilhas |
| 11 Editorial | Janela móvel 24h, deduplicação, frescor de preços/fretes, opt-in e idempotência |
| 12 Infra/Segurança | Rede isolada, segredos, SCA/SAST, concorrência, backup e restore |
| 13 Pesquisa/Ferramentas | Licenças/atribuição, vulnerabilidades, manutenção e PoCs reproduzíveis |
| 14 Auditoria | Testes adversariais independentes e relatório versionado de reteste |

## 6. Reprodutibilidade

```bash
PYTHONPATH=src python -m unittest tests.test_auditoria_independente_fretes -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

O caminho `tests.test_auditoria_independente_fretes` pode exigir que `tests` seja pacote Python; alternativa universal no checkout: `PYTHONPATH=src python -m unittest discover -s tests -p 'test_auditoria_independente_fretes.py' -v`.

As falhas novas **não** devem ser silenciadas com `skip`, `xfail`, mocks que contornem o requisito nem alteração de resultado esperado. Nenhum teste executa rede, deploy ou envio.
