# NIVON — Integração meteorológica MJO/RMM com emissão de previsões NWP

Data de implementação: 21/10/2026. Estado: **offline, sintético, sem homologação ou uso operacional**.

## Fonte de verdade e herança

A PR de integração #55 é empilhada sobre a PR #46, que é empilhada sobre a PR #19. Os quatro arquivos do módulo original da PR #11 foram incorporados por seus **blobs Git exatos**, não por reescrita:

| Arquivo | Blob original da PR #11 |
|---|---|
| `src/nivon/mjo_rmm.py` | `3286dc525eff1092c32cd9ee781f9ff567f7ea14` |
| `tests/test_mjo_rmm.py` | `3ee7f60edee0432393ec7f170e9edd55bfaa627e` |
| `docs/METEOROLOGIA_CAMADAS_MJO_20261020.md` | `d0239e11f127053fe61ddcf7679e7389c9c89706` |
| `docs/CATALOGO_GITHUB_METEOROLOGIA_20261020.md` | `e1bb821bc7fd18050fe57ad41b8b4677951694fa` |

Não aplicar novamente esses arquivos pela PR #11 sem reconciliação de merge na integração central.

## Invariantes científicos

1. O RMM de Wheeler–Hendon é um **índice de diagnóstico**, não um produto operacional de previsão de precipitação, safra, enchente, navegação ou produtividade municipal. A fase é a da fonte, não inventada; amplitude >=1 é uma convenção descritiva de atividade, **não probabilidade regional**.
2. Um snapshot de RMM só pode ser usado em uma emissão `T` quando `publicado_em <= coletado_em <= T`. Uma série histórica obtida hoje não valida como feature disponível numa previsão emitida antes de hoje.
3. O texto do snapshot é conferido por SHA-256; `evidencia_disponibilidade_sha256` é **referência declarada** e não comprovação externa auditada. Datas e identidades autodeclaradas nunca bastam para homologação.
4. O parser original verifica datas, sentinelas, limites físicos, fase e amplitude. A ponte adicional bloqueia texto cujo registro observado seja de dia **posterior** à suposta publicação do snapshot, além de edições com hashes diferentes no mesmo par publicação/captura.
5. Se não há vintage elegível, o resultado é `SEM_VINTAGE_DISPONIVEL` e fase/amplitude são `None`; se não há observação aproveitável, `SEM_OBSERVACAO_DISPONIVEL`; se a idade em **dias de calendário UTC** exceder `max_defasagem_dias`, `RMM_DESATUALIZADO` sem fase utilizável.
6. `RMM_OBSERVADO_FRACO` preserva o sinal fraco sem converter a fase em recomendação operacional. Mesmo com `RMM_OBSERVADO_ATIVO`, `previsao_regional_inferida=false`, `modelo_de_chuva_alterado=false`, `homologado=false`.
7. **Fonte real BOM_RMM não está habilitada no catálogo NIVON**: o módulo rejeita `REAL_AUTORIZADO` até catalogação, direitos e auditoria externa. Nenhum HTTP, background job, token, agendamento ou deploy.
8. Não misturar RMM BOM com índices CPC/EEOF distintos em uma série. A fonte da PR #11 conserva id `BOM_RMM` e amplitude conferida a `sqrt(RMM1²+RMM2²)`.

## Contratos adicionados

- `src/nivon/contexto_mjo_asof.py:indexar_contexto_mjo_asof`: aceita as emissões de previsões e snapshots BOM fornecidos offline. Rejeita capturas duplicadas, versões conflitantes, hash adulterado, ausência de publicação, horas sem fuso, dados posteriores, fontes mistas e IDs repetidos; registra um contexto opcional por emissão.
- `src/nivon/contexto_mjo_asof.py:contextualizar_nwp_com_mjo_asof`: recebe **pacotes de previsão NWP** do contrato `pacotes_chuva_asof` da PR #19, confere SHA, fonte, formato, ensemble 3–100 membros, valores válidos, climatologia existente **até a emissão**, captura antes do início da janela acumulada e liga RMM por **horário de emissão**, e não pelo horário mais tardio em que a previsão NWP foi capturada. Retorna um **sidecar**, sem alterar chuva, probabilidade ou métricas.
- Registro `config/motores_inteligencia.v1.json` na frente METEOROLOGIA e allowlist `registro_motores.py`; produção, scheduling, previsão homologada e inputs reais permanecem OFF.

## Testes e aceitação

`tests/test_contexto_mjo_asof.py` e os testes originais `tests/test_mjo_rmm.py` verificam proveniência declarada, atraso histórico, sinal fraco, defasagem, fuso, conteúdo corrompido, observação posterior à publicação, revisões ambiguamente simultâneas e **vazamento por diferença entre emissão NWP e captura NWP**. Os dados são deliberadamente **100% sintéticos**.

A aprovação CI deve ser verificada no **HEAD final** da PR #55. Testes não demonstram skill preditiva, pois não há relação climática condicionada observada nem hindcast/holdout regional.

## Próxima ação P0

Reconciliar a cadeia empilhada #19 → #46 → #55 com PR #9 e PR #11 no projeto de integração central, coordenando sem reintroduzir o mesmo blob. Em paralelo, preparar os registros de fonte para BOM_RMM com direitos de leitura, armazenamento, pesquisa e eventual uso comercial, sem ativar nenhum coletor antes de aprovação; exigir snapshots históricos reais de publicação/captura (ou disponibilizar somente diagnóstico corrente). Qualquer uso do RMM como feature de modelos agrícolas deve passar por comparação OOS contra baseline, controle de estação/safra/ENSO e auditoria independente.
