# NIVON — infraestrutura e operação (fonte de verdade)

**20/10/2026 · Blueprint em revisão · NÃO É GO-LIVE.** Este diretório é o
ponto de entrada único para a infraestrutura própria do NIVON. Não substitui o
catálogo de fontes, o manifesto de motores ou o controle de release da Holding.

## O que existe e o que não existe

- `inventory.v1.json`: inventário de recursos, responsabilidades e gates;
  todos os ambientes, componentes e autorizações de runtime estão **OFF**.
- `../src/nivon/infra_preflight.py`: pré-voo determinístico que valida
  dependências, estados, custo zero aprovado e controles de segurança, sem rede.
- `compose.yaml` + `docker/Dockerfile.audit`: job temporário, offline,
  perfil `audit`, apenas para conferir o inventário; **não contém workers**,
  API pública ou rotina recorrente.
- `.env.example`: exemplo sem segredos; não é arquivo de produção.
- `runbooks/operacao.md`: requisitos de infraestrutura, recuperação,
  liberação e responsabilidades.

**Não comprova:** assinatura ou quota OCI, VM disponível, serviço iniciado,
dados reais, licença de fonte, backup remoto, scheduler, autenticação, envio,
Ivo em produção ou disponibilidade 24/7.

## Executar verificações sem deploy

Na raiz do repositório (Python >=3.11):

```sh
PYTHONPATH=src python -m nivon.infra_preflight
PYTHONPATH=src python -m nivon.infra_preflight --require-live
PYTHONPATH=src python -m unittest discover -s tests -v
```

O primeiro comando retorna 0 com status
`BLUEPRINT_VALIDO_OPERACAO_BLOQUEADA`: é **validação do documento**, não
aprovação de go-live. O segundo retorna 3 precisamente porque a infraestrutura
não está pronta. Testes não entram na rede.

Contêiner opcional para auditoria, **sem acionar por padrão**:

```sh
docker compose -f infra/compose.yaml config --quiet
docker compose -f infra/compose.yaml build nivon-preflight
docker compose -f infra/compose.yaml run --rm nivon-preflight
```

A construção da imagem obtém uma imagem pública do Docker Hub, portanto
necessita acesso ao registry e validação de digest/proveniência antes de uso
operacional. Em runtime, `network_mode: none` impede rede no contêiner.
Não usar `docker compose up` como deploy do NIVON: a definição contém
somente um job offline. Nenhum serviço é iniciado sem seleção explícita.

## Separação de responsabilidades

- **NIVON:** coleta autorizada do agro, histórico, motores, IVO, briefing,
  API e gateway privados do próprio produto.
- **WhatsApp AI:** ingestão de grupos e relatórios de fretes; interface
  contratual de envio/autorização sem compartilhar banco ou segredos.
- **AI Holding:** governança, estado, custos e releases do portfólio;
  não assume a propriedade dos dados e serviços do NIVON.
- **Segundo Cérebro/Research AI:** pesquisa, evidências e conhecimento
  homologado por contratos, sem escrita canônica direta pelo IVO.

## Princípios irrevogáveis da implantação

1. O notebook nunca participa da execução contínua.
2. Nada de segredos/dados reais em GitHub, CI ou imagem.
3. Fonte pública não implica direito de coleta ou redistribuição.
4. Serviços pagos ou acima da quota grátis ficam bloqueados.
5. Toda coleta precisa de histórico incremental, rastreabilidade, fontes,
   datas e qualidade; ausência de dado não vira zero.
6. Snapshot local SQLite não é backup remoto.
7. Deploy, publicação e envio não são ativados por scripts de documentação.
8. Sem revisão de segurança, homologação e decisão explícita, não há go-live.

Consulte `docs/INFRAESTRUTURA_OPERACIONAL.md` para a arquitetura e
`infra/runbooks/operacao.md` para a execução controlada.

## Controle real de execuções (somente para ensaios sintéticos)

Código em `src/nivon/infra_job_ledger.py` e `infra_smoke.py`:

- Ledger SQLite transacional com unicidade `job_key + due_utc`, hash de entrada,
  tentativas, lease exclusivo, resultado e eventos; estado durável no caminho
  explicitamente escolhido pelo operador.
- `READY → RUNNING → SUCCEEDED/FAILED`; expiração ou conclusão tardia vai
  para `UNCERTAIN` e **não** dispara nova tentativa.
- Recuperação de estado entre processos e ensaio com
  `nivon.backup_sqlite` testados. **Sem** cópia criptografada remota.
- Aceita **somente** `TEST_SYNTHETIC_*`, sem coletor, rede, cron, WhatsApp
  ou execução real. O scheduler futuro deverá usar esses contratos após gate.

```sh
PYTHONPATH=src python -m nivon.infra_job_ledger --status
PYTHONPATH=src python -m nivon.infra_smoke --instante 2026-10-20T12:00:00Z
```

Para testar estado persistente em diretório privado (modo 0700), use
`--db /CAMINHO_PRIVADO/ledger.sqlite`. Não coloque SQLite, WAL ou backups
dentro do repositório, mesmo em branches privadas. **O sucesso do ensaio
não constitui licença, servidor, agendamento, backup remoto ou go-live.**
