# NIVON — Worker isolado (homologação offline)

**Estado: candidato executável, NÃO é stack de produção.**

O componente `src/nivon/infra_worker.py` tem exclusivamente os modos
`self-check` (padrão, sem escrever) e `synthetic-once` (escreve um
contrato totalmente sintético). Não há cliente HTTP, cron, coletores,
envios, cargas portuárias, acesso a cloud ou modelo LLM. A cadeia
`infra/compose.offline-worker.yaml` é segregada da auditoria preexistente
`infra/compose.yaml`; ambas usam perfis explícitos. O digest da base
Dockerfile.worker foi observado nos builds amd64 e arm64 de CI, porém
ainda faltam SBOM, scan de CVEs e release homologada.

## Testes automáticos (não implantam recursos)

`infra_worker.yml` no GitHub Actions executa, sem publicar imagem:
- build local Linux amd64 e execução com rede desativada, usuário não root,
  filesystem read-only, sem capabilities e com limites de CPU/memória;
- `docker compose config --quiet` com diretório efêmero fictício;
- execução sintética duas vezes com pasta privada persistente, comprovando
  `state_written=true` na primeira vez e `false` na segunda;
- terceira leitura do ledger SQLite pelo verificador passivo, de outro
  processo/container; e
- build de camadas ARM64 via buildx sem executar código de outra arquitetura
  (isto **não equivale** a teste funcional em VM ARM64).

Uma falha inicial de teste foi corrigida: o banco mora em diretório
host `0700` pertencente ao UID de serviço 65532, e o usuário comum do
runner não consegue fazer `stat` nesse diretório. O CI usa
`sudo test -s` **somente no runner efêmero**, sem afrouxar
permissões. A conexão de ensaio também passou a fechar explicitamente,
para consolidar o estado WAL.

## Como reproduzir em ambiente autorizado de desenvolvimento

**Não** executar os comandos abaixo na VM de produção. Exigem Docker
local e download da imagem-base pública. O exemplo prepara um diretório
dedicado fora do checkout, sem material sensível:

```sh
sudo install -d -m 0700 -o 65532 -g 65532 /var/lib/nivon/offline-smoke
export NIVON_OFFLINE_STATE_DIR_HOST=/var/lib/nivon/offline-smoke

docker compose -f infra/compose.offline-worker.yaml --profile offline-worker config --quiet
docker compose -f infra/compose.offline-worker.yaml --profile offline-worker build

# Padrão é verificação documental, não inicia rotina contínua
docker compose -f infra/compose.offline-worker.yaml --profile offline-worker \
  run --rm --no-deps nivon-offline-worker --mode self-check

# Somente fixture determinística; executa uma vez e sai
docker compose -f infra/compose.offline-worker.yaml --profile offline-worker \
  run --rm --no-deps nivon-offline-worker --mode synthetic-once \
  --instante 2026-10-20T16:30:00-03:00
```

O UID 65532 deve ser dono da pasta; não usar permissões `0777` como
solução para erro de acesso. Usar host dedicado a testes, não reaproveitar
a pasta `/var/lib/nivon/state` da futura operação real. O contêiner não
é automaticamente reiniciado; nunca criar timers/daemons por conta disso.

## Bloqueios de promoção

- imagem de serviço de produção (módulos e dependências oficiais, não apenas
  `infra_worker`) ainda não construída;
- SBOM, dependências travadas, assinaturas, CVEs e licenças transitivas;
- execução nativa ARM64 em ambiente aprovado e limites/quotas reais OCI;
- database de produção, backups remotos criptografados e restore remoto;
- executor de datasets com direitos por operação, scheduler e observabilidade;
- API privada e deploy/endpoints somente após autenticação e aprovação.

**A aprovação deste teste não promove qualquer gate de produção.**
