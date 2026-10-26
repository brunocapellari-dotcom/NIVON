# Smoke privado e rollback (#290)

`/healthz` verifica somente processo. `/readyz` usa o mesmo leitor/cache do
terminal, responde 200 para competência dentro da janela operacional e 503 para
fonte defasada ou consulta indisponível. Não adiciona uma query quando o cache é
válido. `/api/v1/ferrovia` preserva competência e dados históricos mesmo com
SOURCE_LAG, explicitamente sinalizado; isso não equivale a prontidão.

## Plano, sem rede

```sh
python -B -m nivon.terminal_operacao
```

URL desconhecida ou gates ausentes resultam em BLOCKED e exit 2. O comando não
cria recurso nem inicia deploy. Para avaliar uma implantação já autorizada,
fornecer arquivos **privados** obtidos com os comandos somente leitura:

```sh
gcloud run services describe nivon-terminal --project=nivon-data --region=southamerica-east1 --format=json
gcloud run services get-iam-policy nivon-terminal --project=nivon-data --region=southamerica-east1 --format=json
gcloud run revisions describe REVISAO_ANTERIOR --project=nivon-data --region=southamerica-east1 --format=json
```

Não anexar metadados IAM brutos a PR pública. Configurar a URL conhecida em
`NIVON_TERMINAL_URL`, o SHA completo em `NIVON_TERMINAL_EXPECTED_SHA` e obter
aprovação específica de leitura/custo (`NIVON_TERMINAL_READ_APPROVED` e
`NIVON_GCP_COST_REVIEWED`). Nenhum gate é definido automaticamente.

```sh
python -B -m nivon.terminal_operacao --service-json /privado/service.json --policy-json /privado/policy.json --previous-revision-json /privado/previous.json
```

O plano verifica URL, label, revisão pronta/criada, tráfego 100% na revisão atual,
imagem com tag do commit, bloqueio IAM de invocação anônima e revisão anterior
pronta. Manifests devem pertencer à leitura atual: o plano offline não comprova
frescor nem autenticidade de arquivos. Tag não substitui atestação de digest.
Revisão sem evidência de Ready não é plano de rollback validado.

## Smoke autorizado

Adicionar `--executar-smoke` somente após os gates. Testa primeiro rejeição
anônima (401/403) das três rotas. Se alguma for pública, interrompe antes de
obter identidade. Depois usa token em memória obtido pelo gcloud para as mesmas
rotas. Nunca imprime token, payload privado ou corpo de erro. Redirects são
recusados para não encaminhar Bearer a outro destino. Timeout e limite de corpo
são aplicados. Falha autenticada 401/403 é falha, não sucesso de privacidade.

Este smoke pode levar o cache a executar a query existente: depende de aprovação
de leitura/custo. Não há smoke LIVE executado nesta sessão. Políticas herdadas,+IAM efetivo, custo, disponibilidade e homologação requerem avaliação adicional
da #281/#288. Mesmo SMOKE_PRIVADO_OK mantém `go_live=false`.

## Rollback

O comando só emite plano DRY_RUN com revisão anterior pronta e distinta; nunca
altera tráfego, inclusive se os gates de deploy estiverem aprovados. Após falha,
preservar manifests da revisão atual e da anterior, commit e evidência sanitizada.
Aprovação específica deve indicar serviço, revisão alvo e impacto. Só então um
operador autorizado poderá redirecionar o tráfego no recurso existente e repetir
smoke autenticado/anonimato e auditoria de revisão. Não recriar serviço, elevar
IAM ou habilitar allUsers para recuperar acesso. Não confundir plano offline com
rollback realizado ou testado em produção.
