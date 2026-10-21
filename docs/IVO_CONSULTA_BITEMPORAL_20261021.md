# IVO - consulta bitemporal governada Hermes e Knowledge Factory

Data: 21/10/2026. Status: CONTRATO OFFLINE, TESTES SINTETICOS, NAO HOMOLOGADO. PR #24 permanece draft sobre um commit anterior da PR #7. PR #13 responde pela integracao.

## Componentes reais verificados

Hermes-AI-Platform ja inclui ServiceIdentity e IdentityVerifier (src/hermes/auth.py), PolicyRequest e PolicyDecision (src/hermes/domain.py), CompositePolicyEngine, OPAClient e OpenFGAClient (src/hermes/authorization.py), e um SqlEventStore com outbox e idempotencia em src/hermes/event_store.py.

Atencao: o SqlEventStore consultado NAO implementa, por si so, comprovacao externa de instante nem checkpoint autenticado de cabeca da cadeia de vintages. Nao supor que o sistema ja tenha esse servico. O NIVON ainda nao possui integracao homologada com um backend Hermes rodando.

## Dois relogios diferentes

1. A evidencia tem um tempo historico as-of: quais versoes, snapshots, promocao da Knowledge Factory e revogacoes estavam disponiveis no corte consultado. RegistroVintagesIVO valida a cadeia completa HMAC, a ancora externa datada e um checkpoint externo da cabeca; normalizar_exportacoes_canonicas confere os hashes, os metadados e as quatro datas da fonte.
2. A autorizacao do solicitante e atual: o usuario autenticado precisa possuir o direito de CONSULTAR_EVIDENCIA hoje, mesmo ao perguntar sobre uma serie antiga. GatewayHermesIVO exige origem de identidade trusted pelo servidor, escopo por tenant, registro de recurso e CompositePolicyEngine com OPA e OpenFGA.

A versao anterior exigia que o registro de ACL atual fosse mais antigo que o corte historico; a exigencia era conceitualmente errada. Agora a permissao atual e comparada ao instante de autenticacao. Uma permissao atual posterior a uma evidencia historica pode permitir consulta, mas uma permissao revogada hoje continua negando.

## Novo fluxo

O metodo interno GatewayHermesIVO.consultar_canonicas executa:

- Confirma token usando o verificador fornecido pelo servidor e resolve tenant/projeto/ator exclusivamente por identidade de servico verificada; bloqueia antes de abrir quaisquer snapshots quando nao ha identidade.
- Invoca normalizar_exportacoes_canonicas com um verificador construido por RegistroVintagesIVO para o TENANT autenticado e a operacao CONSULTAR_EVIDENCIA, nunca a partir da pergunta.
- Recusa historia sem atestacao da Knowledge Factory, hashes divergentes, snapshot futuro, head alterado e direitos historicos ausentes.
- Aplica novamente o resource registry e as politicas Hermes para autorizar consulta HOJE; nenhuma consulta pode causar escrita, promocao, treinamento ou despacho de agentes.
- Retorna proveniencia somente de claims visiveis apos policy allow. Em caso de negacao atual nao expoe a fonte, decision_id ou hashes historicos ocultos.
- Identidade e politica externas podem ser doubles em testes, mas nao sao consideradas prontas para producao por esse motivo.

Um token de transporte, snapshots e ledger confiavel so podem ser fornecidos pelo backend. Este metodo nao e endpoint HTTP e nao aceita verificadores ou objetos de policy enviados por LLM.

## Testes e evidencia

tests/test_ivo_consulta_bitemporal.py verifica o fluxo offline completo, com autenticacao unica do token, identidade nao controlada por prompt, tenant cruzado, revogacao anterior e posterior ao corte, ACL atual concedida depois do corte, revogacao de direito atual, politica externa negada, approval pendente, hash adulterado, ancoragem/head indisponivel e sigilo de proveniencia nao autorizada.

A validacao no Actions requer executar a suite Python sintética inteira no SHA final. Testes nao substituem assinaturas reais, implementacao do OpenFGA, chave secreta controlada, check-point externo de auditoria nem license audit.

## Backlog imediato

P0: integrar IdentityVerifier e OPA/OpenFGA REALMENTE pelo Hermes, sem fallback permissivo; autenticar tenant, direitos vigentes e permitir apenas read-only.
P0: obter fontes autoritativas assinadas e independentes de head e ancora temporal, com registro append-only e politica de seguranca; SqlEventStore Hermes atual nao prova essa propriedade.
P0: snapshots Second Brain/Knowledge Factory reais, direitos por operacao e historico verificavel; manter ResearchPackage em estado candidato.
P0: reconciliar PRs #7, #24 e #13; preservar a ponte anual PAM/IBGE, aplicar CI na arvore combinada antes de qualquer homologacao.
P1: gold set temporal/adversarial, RAG de evidencias, citacoes, abstencao, avaliacao estatistica de previsoes e risco operacional.

Sem merge, deploy, secrets, coleta real, integracao paga nem qualquer gasto.

## Aditivo de seguranca — ACL atual de curta duracao (21/10/2026)

O vinculo de recurso retornado por um backend server-side (`VinculoRecursoIVO`) passou a exigir `expira_em` (UTC com fuso); `revogado_em` e opcional e bloqueia se sua data ja foi atingida. Uma permissao sem vencimento expresso **nao** constitui direito atual. Para autorizar a leitura, a janela entre `verificado_em` e `expira_em` precisa ser positiva e de no maximo **cinco minutos**; o vencimento deve ser posterior ao instante da consulta, e a verificacao nao pode ser futura. Tentativas com assinatura temporal malformada, expiracao, revogacao ou TTL longo sao recusadas **antes** de chamar a camada de politica.

Esse mecanismo e defesa adicional, nao substitui validacao da autenticidade do registry nem politicas OPA/OpenFGA atuais. O lease deve ser emitido por um backend que confirma a situacao juridica/contratual **por tenant, recurso e operacao**. Um callback de teste e capaz de fabricar uma permissao; teste sintético nao comprova direito real de dados. O endpoint real deve rejeitar bypass de um registry, expiracao artificial ou clock do cliente. O campo `expira_em` passa a ser obrigatorio **na pratica para toda consulta**, mesmo que a dataclass mantenha default None para detectar consumidores legados e falhar fechado.

Os testes de regressao atuais abrangem: lease ausente, prazo expirado, verificacao antiga, duracao maior que 5 minutos, revogacao ja efetiva, revogacao futura ainda nao efetiva, instantes sem fuso e ocultacao de metadados quando o direito atual e negado.

## Reconciliacao de branches — marco verificavel

A PR #24 incorpora os contratos PAM anuais que avancaram na PR #7, inclusive a ponte anual, catalogo de publicacoes e benchmark anual. Foram criados commits com os dois ancestrais (Git merge commit) **na branch draft do IVO**, sem efetuar merge das PRs na main. A PR #13 nao foi modificada. Em cada reconciliacao, arquivos importados foram confrontados pelos SHA de blob. A aprovacao do CI comprova o estado de codigo, **nao** que as datas reais de publicacao PAM/IBGE, direitos de uso ou resultados do benchmark tenham sido homologados.
