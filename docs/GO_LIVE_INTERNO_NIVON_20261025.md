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
- `scripts/publicar_painel_interno.py`: consulta as três fontes usando `analisar_fontes`, bloqueia alterações de projeto/dataset/bucket, valida que o bucket tem **Public Access Prevention enforced**, grava revisões HTML e JSON imutáveis com precondição de geração e confere SHA após o upload, sem sobrescrever outros objetos.
- `.github/workflows/nivon-go-live-interno.yml`: testes em PR, leitura BQ com WIF e publicação privada em merge na `main`. Agendamento em dias úteis ativo por padrão (12h20 UTC, aproximadamente 08h20 em Mato Grosso), com opção de pausa por `NIVON_PAINEL_INTERNO_AGENDADO=false` nas variáveis do GitHub.

Destinos previstos (não são links públicos):

- `gs://nivon-data-raw-2026/nivon/painel-interno/revisoes/<carimbo>-<sha>.html`
- `gs://nivon-data-raw-2026/nivon/painel-interno/revisoes/<carimbo>-<sha>.json`

Arquivos imutáveis são preservados em `nivon/painel-interno/revisoes/` com identificação SHA e horário. Sem criação de bucket, tabelas, serviço público, conta de serviço, IAM ou domínio. Nenhuma credencial aparece em arquivo ou log.

## Critérios de sucesso verificável

1. CI offline passou, inclusive anti-XSS, ausência de zeros artificiais, não promoção de dados SHADOW e precondições de armazenamento.
2. Workflow da `main` autenticou via WIF nas três leituras do BigQuery.
3. Bucket comprovadamente privado, sem publicação de dados pela interface de repositório.
4. GCS gravou dois objetos imutáveis (HTML e JSON) com SHA-256 e readback verificado.
5. O status `PUBLICADO_SOMENTE_GCS_PRIVADO` aparece na execução do GitHub Actions.

Sem os itens 2–5, o painel está **IMPLEMENTADO, NÃO PUBLICADO**. Uma página protegida acessível via navegador, com login e atualização automática, será a etapa seguinte. O bucket privado não é um website pronto.

## Próxima entrega

Construir camada de acesso autenticado à edição mais recente, sem mover ou reproduzir dados em ambiente público. Gradualmente adicionar fontes CEPEA/IMEA/CONAB com atualização real, diesel ANP, fretes anunciados e malha intermodal, cada um com qualidade, frescor e direitos verificados. Manter VQI, ETA e previsão AIS bloqueados até geocercas auditadas e backtests.

## Correção operacional do segundo ciclo

A edição inicial foi publicada no GCS com quatro objetos em 26/10/2026 (UTC).
Na execução subsequente, a conta federada `nivon-coletor-de-dados` conseguiu
criar revisões imutáveis, mas recebeu HTTP 403 ao tentar **substituir**
`latest.html`: faltava `storage.objects.delete`. Não ampliar IAM por
conveniência de apresentação. O publicador foi corrigido para gravar apenas
as duas revisões imutáveis, fazer readback e informar seu caminho exato no
resumo do GitHub Actions. Repetir o mesmo SHA e corte é idempotente.

**Aviso:** `latest.html` da primeira versão existe, mas deixou de ser
um alias atualizado. Para a edição mais recente, abrir a pasta privada
`nivon/painel-interno/revisoes/` no Google Cloud Storage e selecionar o
último timestamp confirmado no workflow. Uma página web autenticada com
resolução dinâmica da revisão mais recente ainda está pendente. Sem acesso
público, sem chaves JSON, sem permissões IAM adicionais.
