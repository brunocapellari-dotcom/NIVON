# NIVON — Go-live interno inicial

**Primeira entrega:** retrato gerencial HTML privado, produzido diretamente de leituras reais, com acesso limitado ao bucket GCS já existente.

## O que está dentro

- ANTT/SIADE: volume ferroviário declarado nos polos de Mato Grosso, **competência agosto de 2026**, sem interpretar estação como terminal ou somar com rodovia.
- Imbituba: IDs e revisões de programação, sem atribuição indevida de navios operados.
- PortWatch/Panamá: contagem de revisões; volumes e trânsitos continuam **estimativas**, nunca operações realizadas.
- Data/hora UTC do corte, identificação de fonte e ressalvas metodológicas. HTML responsivo, sem JavaScript e sem recursos externos.

Essa primeira versão é **SHADOW, INTERNA e NÃO HOMOLOGADA** para distribuição pública, embora suas três origens tenham leituras reais anteriormente verificadas. Não incluir CEPEA, IMEA e CONAB como valores atuais até confirmação contínua da carga canônica BigQuery; não bloquear o piloto interno por essa dependência.

## Execução

Código:

- `src/nivon/painel_lancamento.py`: valida o contrato de dados e renderiza o relatório sem rede.
- `scripts/publicar_painel_interno.py`: consulta as três fontes usando `analisar_fontes`, bloqueia alterações de projeto/dataset/bucket, valida que o bucket tem **Public Access Prevention enforced**, grava uma revisão HTML e JSON imutável e atualiza os dois arquivos `latest` com precondição de geração, conferindo SHA após o upload.
- `.github/workflows/nivon-go-live-interno.yml`: testes em PR, leitura BQ com WIF e publicação privada em merge na `main`. Agendamento em dias úteis ativo por padrão (12h20 UTC, aproximadamente 08h20 em Mato Grosso), com opção de pausa por `NIVON_PAINEL_INTERNO_AGENDADO=false` nas variáveis do GitHub.

Destinos previstos (não são links públicos):

- `gs://nivon-data-raw-2026/nivon/painel-interno/latest.html`
- `gs://nivon-data-raw-2026/nivon/painel-interno/latest.json`

Arquivos imutáveis são preservados em `nivon/painel-interno/revisoes/` com identificação SHA e horário. Sem criação de bucket, tabelas, serviço público, conta de serviço, IAM ou domínio. Nenhuma credencial aparece em arquivo ou log.

## Critérios de sucesso verificável

1. CI offline passou, inclusive anti-XSS, ausência de zeros artificiais, não promoção de dados SHADOW e precondições de armazenamento.
2. Workflow da `main` autenticou via WIF nas três leituras do BigQuery.
3. Bucket comprovadamente privado, sem publicação de dados pela interface de repositório.
4. GCS gravou quatro objetos com SHA-256 e readback verificado.
5. O status `PUBLICADO_SOMENTE_GCS_PRIVADO` aparece na execução do GitHub Actions.

Sem os itens 2–5, o painel está **IMPLEMENTADO, NÃO PUBLICADO**. Uma página protegida acessível via navegador, com login e atualização automática, será a etapa seguinte. O bucket privado não é um website pronto.

## Próxima entrega

Construir camada de acesso autenticado à edição mais recente, sem mover ou reproduzir dados em ambiente público. Gradualmente adicionar fontes CEPEA/IMEA/CONAB com atualização real, diesel ANP, fretes anunciados e malha intermodal, cada um com qualidade, frescor e direitos verificados. Manter VQI, ETA e previsão AIS bloqueados até geocercas auditadas e backtests.
