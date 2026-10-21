# NIVON — Auditoria independente de frescor na dinâmica de fretes R01

**Data:** 2026-10-21 (America/Cuiaba).  
**PR de implementação:** [#82](https://github.com/brunocapellari-dotcom/NIVON/pull/82), SHA funcional imutável testado `3b57647fdb1d14c8a6db5f38e6121892e5db4111`.  
**PR de auditoria:** [#92](https://github.com/brunocapellari-dotcom/NIVON/pull/92), branch `audit/fretes-dinamica-frescor-20261021`.  
**Teste:** `tests/test_auditoria_dinamica_fretes_frescor.py`, commit `30dadda758ce7559b1f67266771ab96c3480d687`.  
**CI:** [run 39671689462](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671689462).  
**Resultado:** `Ran 1502 tests in 3.154s` — `FAILED (failures=2, skipped=45)` (dois cenários de frescor reprovados; controle do comportamento normal passou).

## Achado NC-AUD-025 — P1: valor historicamente válido com rótulo de tendência atual

O módulo `src/nivon/fretes_dinamica_r01.py` gera `tendencia_atual` e `dinamica` sobre painel econômico pareado, exigindo duas janelas disjuntas e corte `as_of`. Porém, o `as_of` é usado **somente como limite máximo de cronologia**, sem verificar a defasagem entre a **última data efetivamente observada** e esse instante de corte. O mecanismo de janelas reutiliza as últimas 12 sessões disponíveis independentemente de terem terminado na semana corrente ou anos atrás.

### Como foi reproduzido

Usamos 12 datas de observação de 01/10/2026 a 12/10/2026, dois pontos de embarque/transportadoras estáveis, terminal, regime e pedágio constantes; preços sintéticos crescentes com aumento da inclinação da última janela.

| Variação | `as_of` | Esperado | Observado |
|---|---|---|---|
| Controle de recência | 13/10/2026, 15h UTC | Alta histórica e aumento de força, mas não previsão nem publicação | **PASS**. `tendencia_atual=ALTA`, `dinamica=AUMENTO_DE_FORCA`, `publicavel=false`, `homologacao_origem=PENDENTE` |
| Cenário adversarial 1 | 90 dias após último anúncio | `INDETERMINADA`, estado `DADOS_DEFASADOS` ou metadado explícito de frescor comprometido | **FAIL**. `ALTA` e `AUMENTO_DE_FORCA` continuam sem aviso de atraso |
| Cenário adversarial 2 | 365 dias após último anúncio | Mesmo contrato, sem sugerir tendência corrente | **FAIL**. Série antiga mantém rótulo `tendencia_atual=ALTA` sem ressalva específica de defasagem |

A análise continua marcada como **OFFLINE, não homologada, `publicavel=False`**, reduzindo o risco de publicação automática. O problema está na **semântica e na utilidade operacional** do indicador, não na fórmula Theil–Sen em si. Os dois testes vermelhos representam **uma única não conformidade**, e não duas perdas de dados ou falhas de segurança.

## Correção e critérios para aceite

1. Definir regra de atualização baseada em `ultima_referencia_observada` e `as_of`, com parâmetro de SLA/latência por corredor/fonte/calendário ou regra externa auditável; não escolher um número arbitrário como verdade para todos os fretes.
2. Expor `ultima_observacao`, `defasagem_dias`, `status_frescor`, `completude_janela` e `calendario_sessoes_validado` no envelope do motor, deixando explícito quando a série está obsoleta.
3. Quando o dado estiver fora da tolerância, **não** devolver uma `tendencia_atual` corrente sem sinalização inequívoca. Alternativas aceitas pela auditoria: `INDETERMINADA`, status `DADOS_DEFASADOS`, flag `dados_defasados=true` ou `frescor=DEFASADO`.
4. Manter análise histórica retrospectiva disponível, mas com nomes claros (`tendencia_historica`, `ultimo_registro`), nunca apresentá-la como diagnóstico corrente sem refresco temporal.
5. Reexecutar os três testes da PR #92 e a suíte inteira sobre SHA corrigido, mantendo os testes de painel comparável e combate a viés de composição.
6. As NC-AUD-012/013/019/020 de colisões entre provedores na PR #42 continuam P0 e são independentes deste achado; não autorizar integração WhatsApp, consumo de RAW real ou publicação pelo simples fato de corrigir a etiqueta de frescor.

**Evidência e limites:** nenhum dado de frete real, endpoint, credencial, provedor, publicação ou custo foi utilizado. Os resultados testam exclusivamente o contrato offline e dados artificiais. O teste não estabelece um limiar legal nem estatístico de 90 dias — apenas demonstra que lacunas extremas hoje não são rotuladas como tal.

**Parecer:** PR #82 permanece não homologada até remediação das NC de origem/comercialização e inclusão de uma regra verificável de frescor. A auditoria não alterou código produtivo, só testes e documentação.
