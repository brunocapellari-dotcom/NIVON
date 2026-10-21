# IVO — decisões historizadas com integridade e replay as-of (21/10/2026)

**Status: código offline, fixtures sintéticas; sem homologação externa.** PR #24 permanece draft, empilhada sobre PR #7. PR #13 coordena as 14 frentes. Nenhuma chave, segredo, serviço, autorização operacional, merge ou deploy configurado.

## Por que este módulo existe

A ponte `ivo_second_brain_bridge.py` aceita a decisão de um verificador externo, mas isso sozinho não prova se a aprovação, revisão, revogação ou fonte estava disponível no instante de uma consulta histórica. Uma cadeia interrompida também pode ocultar uma revogação posterior. `src/nivon/ivo_vintages_assinadas.py` adiciona controles de integridade e tempo verificáveis **quando os provedores externos forem confiáveis**.

## Contrato read-only

- `EnvelopeAssinadoIVO`: payload JSON canônico (schema estrito, sem campos desconhecidos), versão implícita do domínio `NIVON-IVO-VINTAGE-HMAC-SHA256-V1`, identificador de chave e MAC HMAC-SHA256.
- `RegistroVintagesIVO`: valida todos os MACs com chave fornecida por `resolver_chave(key_id)`; chave nunca fica no código, no payload ou nos logs. A política do backend precisará buscar a chave de um secret manager.
- Hash-chain de envelopes, sequências contíguas, ordenação temporal não decrescente, `decision_id` único por tenant e transição explícita `PROMOVIDO` / `REVOGADO`. A cadeia rejeita mutação, remoção interna, permuta, lacunas ou conflito de sequências.
- `obter_ancora(event_hash)` é **obrigatório** e deve retornar horário comprovado por um sistema **independente** do produtor da decisão. Assinar uma data retroativa não prova que a informação existia naquela data. Uma âncora registrada depois do corte impede que esse evento entre no replay daquele corte.
- `obter_cabeca()` é **obrigatório** e deve retornar o hash da ponta integral da cadeia por sistema de auditoria independente: impede ocultar a última revogação mediante apresentação de um prefixo antigo. A mesma fonte externa deve garantir que o head seja completo e não apenas um valor escolhido pelo requerente.
- A função `autorizador(tenant, consumidor='NIVON', operacao='CONSULTAR_EVIDENCIA')` é compatível com `normalizar_exportacoes_canonicas(..., verificador=...)`. Retorna uma `AtestacaoCanonicaIVO` somente se o último evento ancorado até o instante de corte for PROMOVIDO e coincidir com os hashes exatos. Uma revisão altera o hash aceito; uma revogação nega a consulta no corte posterior.
- `READONLY`: nenhum envio, escrita no vault, cálculo/forecast, pesquisa remota ou LLM. `ResearchPackage` não vira conhecimento canônico e uma decisão assinada não concede licença de publicação.

## Consequências e limitações

**HMAC não é uma assinatura digital assimétrica.** A posse da chave compartilhada permite emitir MACs e portanto não fornece não repúdio entre serviços que detêm essa chave. Para produção, é necessário comprovar custódia/rotação de chaves, separação entre emissor/verificador, expiração, revogação de chaves e persistência durável da cadeia. Avaliar assinatura assimétrica em serviço especializado/KMS antes de homologar.

**Uma data dentro do MAC não é carimbo de tempo independente.** A confiança no replay depende das âncoras e do head obtidos de fonte autenticada/externa. Callbacks Python injetados e simulados nos testes não demonstram essa infraestrutura. Para backtests, o serviço deve preservar a sequência completa histórica de âncoras, cabeças, versões e edições; se não puder comprovar disponibilidade pontual, recusar.

**Duas políticas distintas:** legitimidade histórica da decisão no corte e autorização de consulta **hoje**. Mesmo que um dado fosse consultável no passado, o usuário não poderá acessá-lo hoje caso os direitos tenham expirado; o gateway Hermes com OIDC/OPA/OpenFGA e registry de recursos atuais continua obrigatório. `RegistroVintagesIVO` não substitui nem deriva permissão de uso/redistribuição, e sua saída não é validada para operação real.

**Escopo do replay:** as quatro datas continuam nos registros canônicos do Second Brain (competência, referência, publicação, coleta). Neste ledger acrescem decisão/aprovação, gravação, efetividade e âncora verificada. O histórico de retratações deve ser preservado; `supersedes` e `contradicts` não afirmam causalidade.

## Testes

`tests/test_ivo_vintages_assinadas.py` utiliza HMAC e chaves **sintéticas**; cobre adulteração, key/anchor/head ausente, corrupção/rollback, revogação, revisão, cortes temporais, multitenancy, segregação de operação, sequências, hashes e integração `RegistroVintagesIVO → normalizar_exportacoes_canonicas`. Executar:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ivo_vintages_assinadas.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

Suíte sintética aprovada no GitHub confirma a lógica em código, **não** prova segurança de produtor real, anchoring, disponibilidade de snapshots, licença ou operação. Nenhuma chave real ou URL de serviço real foi utilizada.

## Backlog prioritário após esta rodada

1. **P0** — desenho e homologação do serviço de ancoragem/head independente com autenticação, histórico imutável, chaves governadas e observabilidade (bloqueio externo real).
2. **P0** — source registry/provas de direitos por tenant+operação integrados ao Hermes; expiração/revogação atual contra consultas históricas, testes de isolamento.
3. **P0** — conciliar PRs #7, #24 e #13 sem perder ponte PAM nem os demais motores; testar CI na árvore integrada e passar auditoria independente.
4. **P1** — benchmark RAG com citações, abstenção, recall, conhecimento temporal, defesa adversarial, cobertura e métricas factualidade.
5. **P1** — modelos com dados históricos/licenças e backtesting temporal real auditado antes de previsão operacional.

**Nenhuma ativação automática, nenhum merge e nenhum deploy.**
