# NIVON — Auditoria de previsão arquivada contra frete anunciado (R01)

**Versão:** pesquisa e testes sintéticos, 21/10/2026. **Sem habilitação de produção.**

## Motivação

O pré-voo de cobertura de horizontes em `fretes_cobertura_horizontes.py` mede apenas a existência de dados comparáveis em D e D+7/30/90 dias. Isso NÃO basta para avaliar habilidade preditiva: seria possível "inventar" previsões retroativamente com preços futuros já conhecidos. Uma avaliação precisa confrontar uma previsão previamente emitida com um alvo que amadureceu depois, sem retroativamente preencher a origem.

## Nova interface

`nivon.fretes_previsoes_arquivadas:preparar_compromisso_base_frete` calcula, sem assinar nem escrever em banco, o hash determinístico do snapshot de preços anunciados por identidade econômica, observáveis **até o instante de emissão** (`emitido_em`) do dia comercial da origem em `America/Cuiaba`. Captura os IDs canônicos de ponto e transportadora, o digest derivado do registro original, o valor decimal e horários integrais de publicação e coleta. Emissão real requer um processo externo de custódia de chaves e ancoragem.

`nivon.fretes_previsoes_arquivadas:avaliar_previsoes_arquivadas_frete` recebe **previsões anteriormente arquivadas** pelo usuário/coletor, cada uma com:
- identidade homogênea de corredor, produto, descarga, equipamento, regime PF/PJ, pedágio, fonte;
- `previsao_id`, `modelo_versao`, `emissor_id`, data de origem, data-alvo, horizonte de **dias corridos**, horários `emitido_em`, `registrado_em` e `treinado_ate`;
- `delta_previsto_brl_t` assinado, e `base_snapshot_sha256` do conjunto disponível na emissão;
- `assinatura_hmac_sha256` externa sobre **todos os campos restantes** com separação de domínio. A chave de verificação é passada pelo runtime, NÃO gravada no repositório.

A validação recusa assinatura divergente, origem/alvo errados, registro no ou após dia do alvo, emissão em dia indevido, seleção de preço-base que ainda não estava coletado, mudança de rota/contrato ou previsão duplicada. Reavalia TODAS as ofertas com o contrato da integração R01, sem seleção silenciosa dos preços.

Somente um painel mínimo de **dois pares iguais** entre a data de origem (com disponibilidade comprovada antes da emissão) e a data-alvo (observação até o corte de avaliação) serve de alvo. Calcula a mediana das diferenças BRL/t dos **mesmos pares**, jamais nível médio municipal ou preço contratado. Compara o delta previsto contra o baseline simples de delta ZERO e informa MAE/RMSE por lote. Todos os folds fornecidos precisam ter alvo comparável; nenhum é removido silenciosamente para inflar desempenho.

O `baseline_id` está implícito na definição de **sem mudança de frete base anunciado** e não é preço de mercado ou tonelagem observada. Dados/scores numéricos de fixtures sintéticas NÃO atestam valor preditivo real, e folds com datas-alvo sobrepostas não são independentes. A sobrevivência de pares presentes no alvo pode enviesar a amostra, assim como o viés de divulgação de anúncios.

## Limitações obrigatórias

- A assinatura HMAC confirma apenas integridade da declaração **relativamente à chave confiada**: não prova que o forecast existiu naquela data. Ainda exigem ancoragem independente de tempo, log imutável/append-only, custódia, rotação de chaves, verificação anti-backfill, controle de revogação e replay.
- SHA derivado do painel não prova autenticidade dos bytes RAW, consentimento, direitos de coleta, termos do provedor ou licença de redistribuição. O canal de eventos de WhatsApp exige autorização e assinatura das camadas independentes de direitos e resolução antes de qualquer uso.
- Os dias comerciais não estão comprovadamente completos: ausência de ofertas, saúde do coletor e calendário precisam ser auditados por corredor. O modelo NÃO prevê automaticamente períodos sem anúncios.
- Precisão numérica, regime de frete, calendário, representatividade dos pares, seleção de instrumentos e risco de sobrevivência continuam sujeitos a auditoria.
- É necessária validação **fora da amostra** com emissão observável, holdout purgado e benchmarks relevantes, com alvos apenas depois de maturados, antes de falar em qualidade de previsão.
- Todos os relatórios continuam `publicavel=false`, `habilitado_para_producao=false`, `probabilidades_calibradas=null`, `carimbo_temporal_externo_comprovado=false`, `integridade_raw_provedor_comprovada=false`.

## Execução

`PYTHONPATH=src python -m unittest discover -s tests -p 'test_fretes_previsoes_arquivadas.py' -v` testa contratos, assinaturas HMAC artificiais, origem/target e dados simulados para 7/30/90 dias. O teste cria os compromissos e as assinaturas para fixtures exclusivamente para provar lógica; não simula o histórico real de emissão.

Esta etapa não faz deploy, coleta, envio de mensagens, merge ou novos custos.
