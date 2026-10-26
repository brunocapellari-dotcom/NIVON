# NIVON — Fast Lane de go-live interno sem Vercel

**Corte:** 25/10/2026 (América/Cuiabá). Branch de entrega baseada na `main`, diferente das cadeias grandes de PRs em draft.

## Escopo executável

O primeiro produto operacional reduzido é o **terminal privado no Google Cloud**, com apenas dois módulos:
- **Ferrovia ANTT/SIADE**: painel atual de série histórica consultada em BigQuery existente, com indicação de dados declarados, partial-year e ausência de homologação editorial. O terminal/web `src/nivon/terminal_web.py` já está na `main`.
- **Câmbio BCB PTAX USD**: módulo de aquisição oficial read-only comprovado na [PR #305](https://github.com/brunocapellari-dotcom/NIVON/pull/305) e incorporado ao mesmo terminal. A API `/api/v1/ptax` informa competência, idade e variação disponível. Não converte o dado observado em operação negociada, não publica automaticamente nem armazena o retorno.

Cópia dos módulos PTAX `bcb_ptax.py`, `ptax_plano.py` e `piloto_ptax_readonly.py` + testes foi feita da PR #305, **sem mesclar sua árvore antiga de integração**, evitando duplicidade com as PRs #13/#305.

## Operação segura

O terminal possui rotas `/`, `/healthz`, `/api/v1/ferrovia` e `/api/v1/ptax`. A seção PTAX renderiza **ausência** quando dados estiverem defasados ou inacessíveis. A API PTAX inicia **desligada**; requer `NIVON_PTAX_INTERNAL_READ_ENABLED=true` para consultar o BCB. O HTTP servidor por si só **não** substitui IAM do Cloud Run: a política do deploy continua `--no-allow-unauthenticated` e login privado.

Cache de 30 minutos em memória por instância limita requisições BCB em acesso simultâneo. `/healthz` não consulta BigQuery/BCB, e uma falha de PTAX não desliga o painel ANTT.

## Correção de segurança consolidada

Aplicadas as alterações da [PR #283](https://github.com/brunocapellari-dotcom/NIVON/pull/283) na **mesma branch de go-live**, para evitar dois merges descoordenados:

- `.github/workflows/nivon-go-live-interno.yml`: o job que escreve no GCS não pode disparar por `push` ou por agenda implicitamente habilitada. Requer aprovações `NIVON_PAINEL_INTERNO_WRITE_APPROVED=true`, `NIVON_GCP_COST_REVIEWED=true` e `workflow_dispatch(publicar=true)` ou agendamento aprovado explicitamente.
- `.github/workflows/nivon-terminal-piloto-real.yml`: leitura real GCP somente por despacho manual e variáveis `NIVON_TERMINAL_READ_APPROVED=true`, `NIVON_GCP_COST_REVIEWED=true`.
- `nivon-terminal-go-live.yml` da `main` já condiciona deploy privado ao despacho manual, aprovação de IAM/custos, repositorio de imagens existente e SA somente leitura.

`.github/workflows/nivon-terminal-ptax-fastlane.yml` faz testes HTTP locais do terminal combinado e **um GET oficial BCB**, sem logs de preços, nenhum GCP/BigQuery/GCS, nenhum cron e nenhum artifact com cotações.

## Critérios de aceitação (sem homologar artificialmente)

1. Suíte principal e job Fast Lane aprovados; a consulta real BCB devolve amostra observada recente, sem publicar preços.
2. Terminal web existente atende ANTT e PTAX sem mistura semântica de dado observado com estimado.
3. **Sem efeitos pagos por evento de merge ou push.**
4. GCP: readback da view ANTT, IAM invoker privado, billing e Artifact Registry/Cloud Run em projeto `nivon-data` homologados antes de despachar deploy autorizado.
5. Verificar URL **privada** do Cloud Run autenticando como usuário autorizado e abrir `/healthz` e `/api/v1/ferrovia`; PTAX habilitar somente com avaliação da fonte e autorização de leitura interna.
6. Após estabilizar operação, integrar gradualmente CEPEA/IMEA/CONAB, diesel, meteorologia, frete e marítimo a partir de dados efetivos com histórico e permissions; cada módulo fica indisponível até ter fonte legítima e vigente.

**Fora do escopo de lançamento:** previsão de preços/fretes, AIS completo, dezenas de coletores, WhatsApp automático, licença de redistribuição presumida e acesso público.

## O que ainda não foi realizado

Esta branch **não** executa deploy, IAM, BigQuery real, GCS escrita ou coleta agendada. Evidências de execução do painel no bucket e PTAX real existem independentemente, mas **não são** prova de que os módulos foram integrados num serviço Cloud Run em produção. Os arquivos continuam em PR até revisão e gates. Não há autorização para ativar recursos pagos apenas por pedir aceleração.

### PRs sobrepostas — evitar merge duplicado

- **#305:** fonte PTAX read-only e respectivo teste vivo; esta branch transpõe só os módulos necessários ao terminal existente.
- **#283:** controle de custos/efeitos de workflow; esta branch transpõe o patch.
- **#13:** integração ampla de frentes, **não** bloqueia o go-live privado reduzido com dados já observados.

**Próxima ação material:** uma revisão técnica da PR Fast Lane baseada em `main`, verificar as configurações já existentes e obter aprovação explícita de deploy/custos. Não integrar Vercel.

## Diagnóstico de infraestrutura verificado — 26/10/2026 UTC

Fonte: [GitHub Actions 40261748288](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40261748288) e [diagnóstico do terminal 40262034829](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40262034829). São respostas do pipeline **somente leitura**, não prova de autorização para mutações.

| Requisito | Estado observado |
| --- | --- |
| Dataset BigQuery `nivon-data.nivon_raw` | CONFIRMADO |
| View ferroviária no BigQuery | CONFIRMADO |
| Bucket privado e região do dataset | `southamerica-east1`, confirmados |
| Artifact Registry (nome do repositório do terminal) | NAO_CONFIGURADO nas variáveis do job |
| Service Account de execução do Cloud Run | NAO_CONFIGURADO nas variáveis do job |
| Existência/descrição do serviço Cloud Run | SEM_PERMISSAO para diagnosticar |
| IAM privado do serviço | SEM_PERMISSAO para diagnosticar |
| Estados das APIs Run/Build/Artifact | INDETERMINADO na identidade do job |
| `agro_fonte_stage` | AUSENTE, mas **opcional** para o terminal ferroviário inicial |

O retrato interno foi gravado no bucket privado em [Actions 40257509093](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257509093). Isso **não comprova** que um terminal Cloud Run esteja acessível nem que uma API HTTP da nossa PR tenha sido implantada.

### Gates restantes: ação humana somente onde é material

1. Reconhecer/completar os nomes de Artifact Registry e Service Account **existentes** para o terminal, ou autorizar sua criação após avaliação de custos. Não criar automaticamente recursos de Google Cloud.
2. Conferir permissões read-only da SA em `nivon-data.nivon_raw`, permissões de implantação da identidade GitHub e controles de acesso privado do Cloud Run; a verificação atual indica `SEM_PERMISSAO` ou `INDETERMINADO`.
3. Após revisão técnica da PR e definição de limite de custos, conceder aprovação explícita de deploy e custos nas variáveis do workflow e executar o despacho manual `confirmar_deploy=true`. O script exige `main` e `--no-allow-unauthenticated`.
4. PTAX só liga com **duplo opt-in** `NIVON_PTAX_INTERNAL_READ_ENABLED=true` e `NIVON_PTAX_INTERNAL_SOURCE_APPROVED=true`; fora disso a seção permanece indisponível, sem consulta BCB.
5. Validar com identidade autenticada os endpoints `/healthz`, `/api/v1/ferrovia` e `/api/v1/ptax`; observar freshness e não liberar serviço público.

A PR #283 já foi incorporada à `main` durante esta rodada; a branch foi reconciliada sobre o HEAD atualizado da `main`, **sem duplicar o patch**. A PR #305 permanece como origem dos módulos PTAX, mas não deve ser integrada outra vez sobre esta entrega sem reconciliação.
