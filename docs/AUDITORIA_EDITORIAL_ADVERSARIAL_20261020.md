# NIVON — Auditoria editorial independente da PR #26

**Data:** 2026-10-20  
**Branch auditada inicialmente:** `feat/editorial-preflight-homologacao-20261020` em `03e363965a50db8d99dbc24e97204ab87cf8d604`  
**Branch de testes independente:** `audit/editorial-preflight-adversarial-20261020`  
**PR de auditoria:** #28, base PR #26  
**Workflow de evidência:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39488605454  
**SHA do teste executado:** `3ecf98e3146c00b26244978023b8a9bc93fe2e82`  
**Resultado:** 1036 testes executados, 4 falhas novas, sem skips; o controle positivo passou.  
**Status:** REPROVADO para promoção do preflight como gate confiável de dados correntes. Esta reprovação não significa execução produtiva ou envio; a PR explicitamente permanece offline.

## Hipóteses reproduzidas (não conformidades confirmadas no SHA)

| Identificador | Severidade | Sintoma do teste | Risco | Correção exigida |
|---|---|---|---|---|
| NC-AUD-006 | P0 | Fechamento datado de 20/07/2026 marcado como última sessão foi aceito para revisão em 20/10/2026 | Preço vencido como atual por declaração autoatestada | Validar sessão e calendário por fonte externa confiável, edição/as-of e máximo intervalo explícito; não apenas comparar duas strings informadas |
| NC-AUD-007 | P0 | Anúncio de frete referenciado em 2024 e republicado em 2026 foi aceito para revisão como corrente | Informa frete histórico como referência presente | Classificar anúncio histórico separadamente, validar janela temporal e validade econômica com publicação original distinta de coleta e referência |
| NC-AUD-008 | P1 | Timestamp de referência 19/10 às 23h30 UTC-03 converte para 20/10 UTC e provoca falso bloqueio da sessão 19/10 | Perda de cobertura e inconsistência de fechamento entre fusos | Vincular data da sessão ao calendário e fuso da bolsa/provedor, não a `_instante(...).date()` UTC |
| NC-AUD-009 | P0 | `classificacao_volume=OBSERVADO`, `volume_realizado=True` e texto coerente foram aceitos sem prova operacional individualizada do volume | Volume de referência ou inferido pode ser apresentado como efetivamente realizado | Exigir ID de evidência de operação, fonte e vínculo por evento/corredor/competência, ou rotular o volume como não comprovado |

### Limites de interpretação
- Todas as entradas são **inteiramente sintéticas**; o teste confirma **comportamento lógico do código**, não que um boletim com dados reais tenha sido enviado.
- O preflight atualmente distingue revisão interna de envio. Assim, os cenários demonstram defeitos do **controle de consistência pré-editorial**, não prova de publicação incorreta.
- A nova PR #26 tinha avançado até `aad0354a57e991ceb886619fe8aa01bad973d0ee` durante a rodada. Comparação desde `03e363...` mostrou alterações em pipeline/CLI/testes, sem alteração em `src/nivon/editorial_preflight.py`. Mesmo assim, o SHA de integração final deve ser retestado.
- Uma alegação `fechamento_confirmado=True` ou `direitos_publicacao=True` não substitui prova da infraestrutura de origem; o pipeline E2E precisa ligar esses metadados a documentos/RAW/hash e credenciais autorizadas.

## Evidência red/green independente

```text
test_controle_pacote_sintetico_coerente_apto_somente_a_revisao ... ok
test_p0_anuncio_de_2024_nao_deve_ser_frete_corrente ... FAIL
test_p0_cotacao_de_90_dias_nao_e_fechamento_atual ... FAIL
test_p0_volume_observado_precisa_evidencia_propria ... FAIL
test_p1_sessao_local_antes_meia_noite_nao_e_dia_utc ... FAIL
Ran 1036 tests in 1.522s
FAILED (failures=4)
```

Reprodução no checkout da branch da PR #28:

```bash
PYTHONPATH=src python -m unittest discover -s tests -p 'test_auditoria_independente_editorial.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

## 2º lote de achados — falhas cronológicas de publicação (reteste)

**Novo commit de testes:** `84e1f729be812306ed0743ddc7b1ed1599fd31ab`.  
**Workflow:** https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39489197988  
**Resultado independente:** `Ran 1044 tests in 1.235s / FAILED (failures=6)`. Os quatro achados anteriores permanecem, e dois novos testes foram reproduzidos como falhas.

| Identificador | Severidade | Evidência | Gate requerido |
|---|---|---|---|
| NC-AUD-010 | P0 | Fechamento referenciado às 17h, supostamente publicado às 10h do mesmo dia, foi aceito | Exigir `data_publicacao >= referencia_em` ou contrato expresso de preview/projeção que impeça promover a fechamento observado |
| NC-AUD-011 | P0 | Oferta de frete referenciada às 09h, supostamente publicada às 08h, foi aceita como corrente | Recusar ou segregar anúncio futuro/antecipado e não declarar observado atual sem cronologia verificável |

Os dois testes passaram pelo parser de origem sem erro e **falharam nas expectativas de rejeição**. Não há prova de uso produtivo. O gate temporal deve preservar fusos de referência, calendário econômico e conceitos de *publicação original* versus coleta ou atualização.

**Total no módulo PR #26:** seis casos adversariais de falha (cinco P0 e um P1) mais controle positivo verde.  
**Dependência:** as correções de negócio devem ser integradas ao pipeline editorial e retestadas no SHA de release, sem modificar expectativa dos testes.

## Pendências e responsabilidades

1. **Editorial (PR #26):** corrigir NC-AUD-006, 007 e 009 na implementação, com provas estruturadas verificáveis e testes sobre o calendário da fonte; corrigir NC-AUD-008 sem aceitar sessão inválida ou vintage futuro.
2. **Dados + Mercado + Logística:** garantir contratos para `origem_documento_id`, licenças por operação, janela de validade e sessão real, evidência de embarque/volume realizado e invariantes econômicos.
3. **Direção Técnica:** integrar PR #26 com PR #13 e PRs #18/#21 após conciliar o mesmo modelo de frete/fonte/tempo. É proibido reintroduzir recortes municipais agregados.
4. **Auditoria:** reexecutar os mesmos testes em cada commit candidato, incluindo release final, sem `skip`, e depois testar a cadeia RAW autorizado → parser → proveniência → briefing offline → outbox sem envio real.
5. **Infra/segurança:** `main` continua `protected=false` e sem rulesets evidenciadas na rodada; gate P1 até configuração segura e verificada.

**Política:** zero aprovação de operação apenas por testes sintéticos verdes; nenhuma tentativa de envio, coleta restrita, pagamento ou deploy na auditoria.
