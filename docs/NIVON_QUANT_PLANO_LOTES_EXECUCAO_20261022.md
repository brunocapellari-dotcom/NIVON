# NIVON — Ciclo de execução em lote: Quant, Fretes R01 e Mercados

**Corte:** 22/10/2026, América/Cuiabá. **Escopo:** desenvolvimento
reversível e offline; sem deploy, publicação, credenciais, serviços pagos ou
merge na main. Um comando do usuário não é requisito para cada teste: os
workflows de CI associados a novos commits validam automaticamente a árvore.

## Prioridades de execução e teste — em blocos

| Ordem | Execução | Critério de teste | Situação no corte |
|---|---|---|---|
| P0.1 | Corrigir R01 na PR #30, exigindo descarga e PF/PJ no contrato e em cada linha | Descartar mistura, ausência de condição e alteração de identidade sem falsa tendência | Implementado na branch PR #30: `8b351202`, CI [39889891470](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39889891470), 1314 testes 0 falhas |
| P0.2 | Adicionar origem RAW verificável no Quant | SHA256 dos **bytes originais**, recibo HMAC do coletor confiável, emitido antes da coleta, mesmo registro/oferta/publicação/fonte | Implementado, `fretes_raw_ponte_quant.py`, testes adversariais, **somente offline** |
| P0.3 | Sincronizar Mercados com Quant em lote | Comparação de árvore e blobs, zero conflito, testes conjuntos | Integrado até SHA Mercados `687ce367ca5f88fa07f0e050440812f4c5451d7b` via `210da61d` |
| P0.4 | Criar orquestrador de fretes usando módulos reais | Entrada única → consolidação → painéis R01 por corredor comercial → séries por entidade; proibir qualquer média municipal | `pipeline_fretes_quant.py`, `tests/test_pipeline_fretes_quant.py`, implementado |
| P0.5 | Auditar regressões juntas e integrar documentação | CI de todo checkout; corrigir testes no mesmo ciclo; registrar SHA e próximos bloqueios | Lote de CI em execução final; conferir HEAD exato após documentação |
| P1.1 | Resolver atestação do conteúdo do anúncio contra parser original independente | RAW precisa provar semanticamente preço, origem/destino, produto e condição comercial, não só bytes/metadata; conservar rejeição ambígua | **Não homologado**, depende do coletor e corpus RAW autorizado |
| P1.2 | Alinhar base definitiva das PRs #18, #20, #21, #30 | Reconciliação de código sem duplicar motores, regressão do conjunto final em mesmo SHA e sem sobrepor contratos | **Pendente**: PR #30 segue em árvore independente; issue #25 aberta |
| P1.3 | Provar calendário, licenças e histórico de vintages de CEPEA, IMEA, CONAB, BCB/CME | Captura autorizada + direitos + snapshot externo imutável + disponibilidade point-in-time e amostra fora da seleção do modelo | **Bloqueado por dados e evidência de fonte** |
| P2 | Calibração, regime, drift e validação produtiva | Benchmark temporal, Brier e calibração fora da amostra, holds intocados e gates humanos de publicação | **Não homologado** |

## Código de fato entregue neste ciclo

1. Na **PR #30**, contrato R01 `tendencia_frete_anunciado` exige
   `descarga_entity_id` e `regime` (PF/PJ/NAO_INFORMADO), rejeita
   observações divergentes e registra ambos no retorno. Os testes da
   própria PR foram atualizados e executados.
2. Na **PR #20**, `fretes_raw_ponte_quant.py` valida recibos HMAC com
   chave externa ao evento, domínio exclusivo, todos os campos tipados,
   SHA do RAW real recebido como `bytes`, e temporalidade
   `publicado <= capturado <= emitido <= coleta <= as_of`.
   Rejeita pacote parcial, duplicado, adulterado, assinatura incorreta,
   chave não confiável, republicações sem prova individual e metadados
   retroativos. Não armazena os bytes e não gera segredo real.
3. Em `pipeline_fretes_quant.py`, um lote tipado `OfertaFrete` é
   consolidado uma única vez, separado por **identidade econômica
   individual** para séries as-of e por **condição comercial homogênea**
   para painel R01. Sem RAW assinado o Quant bloqueia; com RAW de fixture
   só prepara avaliação **offline**, nunca previsão real.
4. A base Mercados foi reconciliada até SHA congelado
   `687ce367ca5f88fa07f0e050440812f4c5451d7b`: coexistência,
   continuidade, orquestração em lote e migração reversa PTAX. A PR #21
   pode receber novos commits depois do corte, que precisam de CI próprio.

## O que os testes NÃO comprovam

- HMAC verifica apenas a alegação do **coletor com chave confiável**.
  Não prova autoria original do anunciante, veracidade do preço, conteúdo
  semântico completo da mensagem, direitos ou WORM externo independente.
- Um SHA derivado do painel ou um hash sintático inventado não é
  equivalente a SHA dos bytes originais.
- Anúncios não são preços negociados/contratados. Município é apenas
  agrupamento geográfico de estabelecimentos; nunca unidade para média
  de valor de frete.
- Comparar grupos com descarga, PF/PJ, produto, equipamento ou pedágio
  diferentes não autoriza criar tendência, nem uso do percentual de
  retorno sem base física justificada.

## Regra para próximos ciclos sem prompts unitários

- Antes de escrever: ler HEAD/CI das PRs e o manifesto
  `config/execucao_quant_lotes.v1.json`.
- Executar **o próximo lote inteiro**: editar módulos e adaptadores,
  integrar contratos, cobrir cenários de falha, testar no GH Actions,
  reparar, atualizar manifesto e comentários com SHA.
- Não parar entre arquivos, entre testes ou após um commit verde.
- Só interromper por conflito real, ausência de evidência/autorização,
  custo, credencial ou risco irreversível.
- Não afirmar que dados reais estão integrados nem que um modelo
  é apto a publicação por suíte sintética aprovada.

## Evidência de CI de integração ampliada — 22/10/2026

A PR #20 incorporou **por SHA** o conjunto Mercados
`cfbea57b89f6e2eaaa3958ca1f482c3e048daa07`, incluindo a etapa
adicional de testes de ponta a ponta PTAX no workflow existente:
`.github/workflows/testes.yml`, com `permissions: contents: read`,
nenhum novo disparo de rede/fonte real e execução apenas com fixtures
sintéticas. O script
`scripts/ensaio_ptax_integrado.py` executou dez etapas,
incluindo `backup`, `restore`, leitura decimal/legada e migração
reversa em banco SQLite em memória, impedindo promoção editorial.

- Merge de corte Mercados: `5a840abab6ed78e933df565f6d20bf030931c04a`.
- [CI 39890911522](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890911522):
  **SUCCESS, 1.666 testes, 0 falhas, 5 skipped**, etapa adicional
  `ENSAIO_PTAX_E2E_APROVADO_APENAS_SINTETICO` com as dez etapas;
  `fonte_real_coletada=false` e `publicavel=false`.
- Na mesma frente Quant, os testes de orquestração em lote dos anúncios,
  de recibos RAW e de separação econômica foram executados como parte da
  suíte e bloqueiam documentação/prova incompleta ou adulterada.
- Na PR #30, o HEAD `8b351202e9ead030dd862dd45e8e6afd86ecc378`
  foi validado em [39889891470](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39889891470):
  1.314 testes, 0 falhas, 5 skipped, exigindo descarga e PF/PJ.

**Corte congelado:** a PR #21 pode continuar recebendo novas alterações.
O fato de um HEAD novo surgir não invalida o CI de um corte anterior,
mas seus commits adicionais não estão auditados por esta suíte.
Não adicionar automaticamente novos workflows, serviços de rede ou
mudanças de licenciamento sem inspecionar os deltas.
