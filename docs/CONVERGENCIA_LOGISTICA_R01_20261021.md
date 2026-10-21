# NIVON — Convergência R01 de Logística e Mercados — 21/10/2026

## Linhagem e escopo executado

- **Árvore base efetiva:** PR #30 `integration/nivon-mercados-reconciliacao-20261020` commit `53544dc65317535e8c0ba6fdf238fd8539d468ac`.
- **Origem dos módulos isolados:** PR #18 `feat/logistica-fretes-diesel-corredores-20261020` commit `d78e5618e81b28b4f1d17a5815775bea20b167bd`.
- **Integração:** branch `integration/nivon-logistica-r01-convergencia-20261021`, PR draft #42. Commit inicial `d62c5a51a60af9d902c8ab29cc2a6f44d8eac606`, que preserva integralmente a árvore da PR #30 e adiciona 17 arquivos/revisões selecionados da PR #18.
- **NÃO** executamos merge das PRs #18/#30 nem qualquer atualização em `main`. A PR #42 é dependente da PR #30 e aguarda reconciliação no integrador central, revisão e homologação.

## Motor estatístico único

`src/nivon/tendencias_mercados.py::tendencia_frete_anunciado` é a implementação **canônica única** da lógica R01 para fretes. Estende o algoritmo de pares estáveis da PR #30 com `descarga_entity_id` e `regime` obrigatórios por invocação e por observação, além do controle preexistente de origem/destino IBGE, produto, equipamento, pedágio, fonte, valor e natureza OFERTA.

A interface de `src/nivon/fretes_integracao_r01.py` prepara registros normalizados usando `fretes_painel_pr30.py` e delega ao **mesmo método canônico**. O arquivo duplicado `fretes_tendencia_pareada.py` não foi incorporado. As regressões adicionais daquele port foram preservadas como `tests/test_fretes_tendencia_r01_contract.py`, adaptadas para o método único.

**Métrica:** mediana das VARIAÇÕES pareadas de observações dos mesmos pares de estabelecimento de embarque + transportadora ao longo da janela; não calcular média/mediana de níveis de fretes anunciados por município. Alterações de composição dos pontos não constituem variação de preço. O resultado é descritivo, `publicavel=false`, sem probabilidades calibradas, não é frete contratado ou tonelagem movimentada.

## Contrato observado: fretes anunciados

`fretes_adapter_whatsapp.py` exige atestações externas HMAC de `DIREITOS` e `RESOLUCAO`, ligadas ao SHA-256 do evento completo e à versão; fonte, timestamp, ponto de embarque, transportadora, destino de descarga, produto, regime, equipamento, preço base, pedágio e atualidade comercial verificada no conteúdo original são validados. Isso é implementado e testado **somente offline**, usando chaves fictícias nos testes. Não prova consentimento, licença, autenticidade do emissor real, entrega de mensagens ou atualização da API WhatsApp.

`fretes_registros.py` preserva publicações, registros e ofertas econômicas individualizadas, sem taxa média municipal. `fretes_painel_pr30.py` não confunde preço base com cheio, não mascara pedágio divergente, rejeita `as_of` intradiário anterior à coleta e origem comercial antiga reencaminhada. Preserva hash **derivado** para rastreamento de transformações, não o confunde com prova RAW.

O teste integrado `tests/test_fretes_whatsapp_r01_e2e.py` demonstra 12 eventos artificiais de duas transportadoras e dois pontos de embarque em seis dias, com assinatura externa simulada → adaptador → registros comerciais → R01 pareado. Inclui adulteração de resolução assinada e anúncio originalmente datado de 2024 republicado em 2026.

## Diesel e fontes reais

Incluídos os módulos `anp_semanal_store.py` (vintages oficiais LPC, separado de `anp_diesel_store.py` com semana de CSV mensal inferida) e `diesel_pressao.py` (sensibilidade hipotética de custo do diesel por tonelada, nunca frete contratado). **O parser semanal da PR #8 NÃO foi incorporado à árvore combinada nesta integração**. Não afirmar que está conectada a coleta ou já existem três arquivos XLSX reais homologados.

**Evidência GitHub Actions:**
- Commit `d62c5a51a60af9d902c8ab29cc2a6f44d8eac606` → run #39598603609: 1.407 testes, 0 falhas, 5 ignorados.
- Commit `16160d49d4b7c774218e411aba9080220be0b3b5` → run #39598951780: 1.410 testes, 0 falhas, 5 ignorados, incluindo teste E2E sintético; parser não recebe dados reais.
- Jobs ANP real, ANTT, CONAB e bibliotecas opcionais foram **skipped** conforme gatilhos predefinidos.

## Pendências e gates para promoção

1. **P0 integração técnica:** reconciliar a PR #42 na branch central de integração do NIVON, incluindo demais PRs dependentes, sem substituir contratos compartilhados ou reintroduzir mediana de fretes municipais; executar a CI no SHA final da árvore promovida.
2. **P0 auditoria independente:** revisar método R01, isolamento tenant/empresa, deduplicação de oferta, validade comercial, atestações, assinatura e resolução canônica. O registro `OfertaFrete` não possui tenant_id explícito: garantir isolamento pelo Gateway/controlador antes de análises multitenant.
3. **P0 autorização de produção:** conectar provedores somente por meios oficiais ou juridicamente autorizados; comprovar direitos de conteúdo, confiabilidade do atestador, políticas de revogação/rotação de chaves, clock, replay e auditoria do RAW. HMAC de teste não comprova autorização real.
4. **P0 ANP:** integrar parser semanal da PR #8 e historizar ao menos três XLSX oficiais obtidos legalmente com layout, unidades, direitos de armazenamento/redistribuição e datas reais de publicação verificadas. Sem essa evidência, `publicavel=false`.
5. **P1 malha logística:** validar via DNIT/SNV, ANTT e concessionárias a distância dos corredores, pedágios vigentes por categoria e sentido, configurações de caminhão e hipóteses de consumo diesel, com datas de referência/publicação/coleta.
6. **P1 ciência e modelos:** criar backtests point-in-time em múltiplos corredores e janelas, medir estabilidade de painel e viés de seleção de fontes, sem afirmar probabilidade de alta/baixa até calibração empírica.

**Operação:** 100% offline, sem deploy, sem merge em main, sem redes sociais reais, sem integração paga, sem ativação de cron ou coleta. O aumento de testes sintéticos não equivale a homologação de dados reais.
