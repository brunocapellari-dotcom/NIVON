# NIVON — Marco de integração parcial IVO / PAM / Briefing

**Referência:** 21/10/2026. **Estado:** candidato draft, somente código e testes sintéticos; sem dados de produção, homologação, merge de PR, deploy, coleta de rede ou custos.

## Recorte de versões verificável

- PR #7, checkpoint de conhecimento + PAM `b37b2e2413e30396de9258b92999511989fedfc4`.
- PR #24, checkpoint da fronteira IVO/Hermes com a PR #7 como ancestral: `cae5c43d8d7ba83e0b6138638565a25518672fdf`.
- PR #13, integração central das 14 frentes, sem qualquer alteração direta pela candidata: `9f1a5e0ded09ac2246cc83b764ddb60f44436986`.
- PR #78: candidato preserva ancestrais das PRs #13 e #24 com histórico Git de dois pais; o delta de arquivos depois da PR #24 limita-se a 3 caminhos da PR #13 e ao teste de permissões IVO/briefing.

## Correção temporal: erratas PAM publicadas depois do corte

Em `src/nivon/ivo_radar_erratas_pam.py`, o replay de uma data retrospectiva agora **omite integralmente** avisos de errata cuja data oficial declarada é posterior ao corte. Antes, as erratas futuras eram retornadas com um campo booleano falso; os IDs, URLs e datas futuras vazavam e permitiam uso de informação que não existia na época.

Para cada data consultada, um aviso entra somente se `notice_date <= corte`. O status `SEM_ERRATA_NO_CATALOGO_LIMITADO` não significa ausência comprovada de erratas: o índice é parcial, documentos oficiais não foram arquivados e as datas da fonte ainda dependem de atestação externa. A implementação preserva `treinamento_autorizado=False`, `evidencia_digital_arquivada=False` e `reconstrucao_valor_anterior_possivel=False`.

A regressão `tests/test_ivo_radar_erratas_pam.py` cobre ausência completa de metadados futuros, limite exato no dia do anúncio e replay antes da data de referência. Nenhuma evidência numérica anterior ou posterior foi inventada.

## Coletor pontual SIDRA/PAM introduzido pela PR #7

`src/nivon/ivo_pam_coletor_pontual.py` reutiliza planejamento e normalização SIDRA já existentes. A implementação permanece não acionada: nenhuma chamada externa foi realizada nesta rodada.

Na forma testada, o módulo exige **catálogo IBGE_PAM explicitamente habilitado e collection_authorized=True**, referência declarada de direitos de COLETA e ARMAZENAMENTO, URL HTTPS permitida, uma única requisição, proibição de redirecionamentos, proxy/cookies desativados, limite de tamanho, tipos MIME admitidos e plano territorial/cultural canônico. A resposta é `CAPTURA_PONTUAL_PAM_QUARENTENA_NAO_HOMOLOGADA`, não dado canônico nem licença validada. A fonte de direitos é callback/objeto local, **não** confirmação jurídica.

A suíte `tests/test_ivo_pam_coletor_pontual.py` usa transporte simulado, sem internet; cobre fontes desativadas, acesso sem direitos, URLs adulteradas, formatos/limites, PDF falso, arquivo legado e conteúdo SIDRA especial. A existência de método HTTP no repositório não indica execução ou integração com serviço externo.

## Separação entre consulta, publicação e entrega

Os testes `tests/test_integracao_ivo_briefing.py` exigem explicitamente direitos diferentes para `CONSULTAR_EVIDENCIA`, `PUBLICACAO_DERIVADA` e autorização opt-in de envio. A consulta histórica IVO e a autenticação Hermes são limites distintos; o coletor PAM não está conectado a publicações ou a novos motores de previsão.

## Evidência CI anterior à publicação desta documentação

No código da PR #78 em `38979babb95aed06b2180bf3baa73bc48a767fe0`, o workflow [39671529969](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39671529969) concluiu `validar-nucleo` com **1.309 testes executados, 1.301 aprovados, 8 ignorados e zero falhas**, incluindo 17 testes do coletor. As inspeções ANP/ANTT/CONAB e mapa permaneceram skipped.

## Pendências P0 que impedem homologação

1. Confirmar permissão de coleta, armazenamento, consulta e eventual publicação **por fonte, produto, operação e finalidade** em sistemas reais; não confiar na flag de teste nem presumir licença por se tratar de projeto não comercial.
2. Ancoragem externa independente de vintages: checkpoint de cabeça, carimbo do tempo, custódia e rotação de chaves.
3. Integração de servidor OIDC, direitos ACL atuais, OPA/OpenFGA com política de owner approval corrigida na PR Hermes #35 e testes E2E de identidades reais.
4. Snapshots numéricos históricos originais e corrigidos, publicações oficiais, erratas e proveniência de datas; os anúncios do IBGE não substituem bytes preservados.
5. Auditoria e conciliação das demais frentes da PR #13. Preservar o isolamento da `main`, custo zero e homologação humana antes de qualquer deploy ou execução de coletores.
