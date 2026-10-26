# NIVON — Protótipo de consulta IVO (não é o terminal de go-live)

**ATENÇÃO — Decisão de integração 25/10/2026:** a main já contém o terminal web CANÔNICO `src/nivon/terminal_web.py`, com dados ferroviários ANTT reais via BigQuery e fluxo Google Cloud Run privado. Este documento descreve um **protótipo independente** de painel/IVO desenvolvido na PR #78, que **NÃO deve ser implantado como segundo frontend**. Para go-live real usar [issue #281](https://github.com/brunocapellari-dotcom/NIVON/issues/281), [PR #306](https://github.com/brunocapellari-dotcom/NIVON/pull/306), `docs/GO_LIVE_PRIVADO_NIVON_20261025.md` e `scripts/deploy_terminal_privado.sh` da main. Reaproveitar apenas o gate editorial e o planejador IVO de forma compatível com o terminal existente, após resolver o P0 de URL privada. Os comandos Cloud Run abaixo são **referência técnica de protótipo, NÃO roteiro oficial de implantação**.

**Corte de engenharia:** 25/10/2026. **Não confundir:** MVP implementado e testado em CI **não** significa serviço implantado, go-live público, autenticação validada em Google Cloud, coleta real ou acesso a cotações CEPEA/IMEA/CONAB.

## Escopo release 0 (escolha deliberada para reduzir caminho crítico)

Primeira versão utilizável em ambiente **privado/autenticado**:

1. **Painel NIVON** com status claro, indicadores autorizados e briefing preparado (sem WhatsApp).
2. **IVO** com formulário para planejar consulta por soja, milho, fretes, clima e cadeias integradas. Hoje o IVO **roteia frentes e dependências**, não consulta preço nem prevê resultados.
3. **API somente leitura**: `GET /healthz` (saúde do processo), `GET /api/status` (produto/edição), `GET /api/edicao` (somente edição elegível e aprovada) e `POST /ivo` (planejamento lexical, sem LLM/rede).
4. **Gates de publicação**: sem `NIVON_RELEASE_APPROVED=true`, sem `NIVON_RELEASE_FILE` ou sem o SHA-256 exato fixado em `NIVON_RELEASE_SHA256`, a edição não aparece. Edição com mais de uma hora, timestamp futuro, rejeições editoriais, notícia fora de 24 horas, indicadores sem direitos ou fontes inválidas é recusada integralmente.
5. **Privacidade da aplicação**: nenhuma função de coleta, transmissão WhatsApp, segredo embutido, publicação autônoma ou alteração no ledger. UI HTML escapa entradas; endpoints sem cache, referrer ou iframe. A aplicação não implementa login local: **é proibido expor à internet sem proxy/IAM que verifique cada invocação**.
6. **Fretes**: excluídos da release 0 para impedir perda de identidade de transportadora/ponto de embarque. A solução definitiva publicará registros individuais, nunca média municipal, após aprovação editorial da fonte e da operação.

## Estado de engenharia

| Frente | Status verificável | Próximo gate |
|---|---|---|
| HTTP e interface IVO | Implementados e testados localmente | Teste autenticado após deploy |
| Briefing com fontes e janela temporal | Implementado, condicionado a pacote de entrada | Ed. real com fontes, direitos e datas verificados |
| Docker não-root com fonte/config | Imagem construída no CI, sem push | Registry/Cloud Run privado |
| CI E2E local | Servidor HTTP, edição aprovada de **fixture**, tamper fail-closed | Smoke de contêiner completo |
| Google Cloud | Não implantado, sem WIF/custos confirmados aqui | Autorização operacional e IAM |
| WhatsApp e IVO analítico | Fora da release 0 | Conectores, consentimento, licenças e E2E em produção |

## Uso local sem publicar na internet

```bash
# A partir da raiz do repositório
PYTHONPATH=src python -m nivon.mvp_server
# Navegador: http://127.0.0.1:8080
# Sem variáveis de release -> painel e IVO somente;
# GET /api/edicao retorna 503, como esperado.
```

Ou para testar o contêiner sem expor ao host remoto:

```bash
docker build -t nivon-mvp:local .
docker run --rm --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:8080:8080 \
  -e NIVON_PRIVATE_DEPLOY_APPROVED=true \
  nivon-mvp:local
```

O `Dockerfile` não copia arquivos de usuários, secrets ou `.git`. `NIVON_PRIVATE_DEPLOY_APPROVED=true` **não é autenticação**: indica que o operador garante a proteção por IAM/rede. É obrigatória autenticação externa antes de qualquer acesso não local.

## Preparação de uma edição real

Contrato `nivon_mvp_edicao_v1`, com **exatamente** estas chaves: `schema`, `edicao`, `gerado_em`, `fontes`, `noticias`, `indicadores`, `fretes`. `fretes` precisa ser `[]` na release 0. Reutiliza `briefing_composto.montar_briefing` e o filtro de notícias de 24 horas. Sem notícias elegíveis, não inventa manchetes. Ao publicar, o operador precisa:

- Auditar cada informação e direitos **LEITURA/RESUMO/PUBLICACAO_DERIVADA**, com evidência externa; os campos dentro do JSON sozinhos não atestam licença.
- Validar `gerado_em` com fuso, versão, proveniência e referências atuais.
- Fixar SHA-256 exato dos bytes originais no ambiente de execução, aprovar a edição e disponibilizar `NIVON_RELEASE_FILE` em volume privado ou imagem revisada. Rotacionar o SHA requer nova configuração do serviço; **o serviço não tem autosserviço de publicação**.
- Acompanhar expiração da edição (1 hora) e monitorar o retorno `503` após expiração. Quando não há edição, o IVO de planejamento permanece disponível.

Não colocar dados restritos, senhas, tokens, fonte licenciada ou IDs pessoais em repositório público. O SHA fixado evita troca acidental do arquivo aprovado, mas **não é assinatura digital nem validação jurídica por si só**.

## Handoff Google Cloud Run, só mediante autorização de custo/IAM

**Não executar estes comandos até confirmar projeto, billing/limites, service account, permissão, acesso privado e orçamento aprovado.** Cloud Run, Cloud Build, tráfego/egress e Artifact Registry podem incorrer em custos mesmo se `min-instances=0`. Não implantar no Vercel.

Exemplo da política de implantação, para operador autorizado e `PROJECT_ID`, `REGION`, `SERVICE` e `SERVICE_ACCOUNT` já definidos:

```bash
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --service-account "$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --ingress all \
  --max-instances 1 \
  --min-instances 0 \
  --concurrency 1 \
  --cpu 1 \
  --memory 512Mi \
  --timeout 30s \
  --port 8080 \
  --set-env-vars NIVON_BIND=0.0.0.0,NIVON_PRIVATE_DEPLOY_APPROVED=true
```

**O comando é documentação não executada**, não pressupõe projeto/cloud autenticados nem custo zero. Cloud Run IAM deve exigir usuários/grupos de invocação explicitamente autorizados. Não habilitar `allUsers` e não desativar autenticação para ganhar velocidade. O serviço acima roda **sem edição real**, permitindo validar interface, IVO e disponibilidade em ambiente privado antes de liberar dados.

## Gate operacional mínimo de release 0

- [x] Interface web e roteador IVO funcional em código.
- [x] API read-only e edição fail-closed com SHA/janela.
- [x] Imagem Docker construída em GitHub Actions sem publicar imagem.
- [x] Smoke HTTP real em localhost, incluindo fraude de SHA, sem chamadas externas.
- [ ] Executar contêiner restrito e HTTP em GitHub Actions (resultado depende de CI do SHA final).
- [ ] Cloud Run privado configurado com billing e IAM aprovados, URL real e evidência de resposta `/healthz`.
- [ ] Usuário autenticado consegue acessar `/` e `POST /ivo`, sem divulgação de dados.
- [ ] Uma edição real elegível é aprovada, fixada por hash e servida; confirmar frescor e licença em fonte externa.
- [ ] Monitoramento operacional, orçamento/alerta de custos, rollback e suporte de operação definidos.

**Não liberar fretes, previsões, AIS ou WhatsApp apenas porque esta aplicação passou no CI.** Go-live do MVP privado e go-live integral do NIVON são marcos diferentes.

## Próximos lotes de execução

**P0:** Cloud Run privado, identidade/autorização, smoke com URL real e rollback. **P1:** alimentar edições continuamente com dados de direito aprovado (iniciando CEPEA, IMEA, CONAB conforme contratos por uso, sem tratar Google Drive histórico como fonte atual). **P1:** editor de fretes individualizados e conectores de preços/câmbio. **P2:** IVO com consultas realmente executadas sob Hermes e briefing WhatsApp com consentimento/template, sem mudar gates.
