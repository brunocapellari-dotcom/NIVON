# NIVON — Vigência temporal efetiva antes de reservar envio

**Data:** 23/10/2026. **Escopo:** PR #53, processamento offline e outbox SQLite.
**Status:** código de segurança implementado com fixtures, sem habilitar transporte.

## Problema corrigido

Anteriormente, o preflight limitava notícias à janela de 24 horas a
partir da geração do briefing, mas uma autorização com validade posterior
podia abrir caminho à reserva de uma edição histórica: a outbox não
mantinha a hora original da notícia mais antiga.

Uma assinatura HMAC de direitos ou aprovação editorial não garante que
o conteúdo continue atual no instante do eventual POST.

## Regra implementada

Em `vigencia_editorial.calcular_vigencia_editorial`:

- Cada notícia deve ter `fonte_id`, `url` e `publicado_em` com horário e fuso.
- Rejeitar publicação futura ou anterior a 24 horas em relação à geração.
- `noticia_mais_antiga_utc = MIN(publicado_em das notícias presentes)`.
- `valido_ate_utc = MIN(noticia_mais_antiga_utc + 24h, gerado_em_utc + 24h)`.
- O limite final é **exclusivo**: no próprio horário de vencimento
  a edição já está bloqueada. O fuso é convertido para UTC na comparação.
- Nenhuma extensão ou renovação implícita é criada por nova aprovação,
  tentativa repetida, replay, mudança de horário do template ou reinício.

O preflight `avaliar_previa_editorial` calcula a publicação mais antiga
a partir das notícias verificadas e inclui seu timestamp no relatório.
`registrar_autorizacao` recusa notícias ausentes/inconsistentes e compara
o mínimo calculado com esse relatório. A tabela
`nivon_vigencia_editorial` persiste `gerado_em_utc`,
`noticia_mais_antiga_utc`, `valido_ate_utc`, SHA editorial e SHA
canônico das identidades/timestamps das notícias; não guarda texto
nem telefone. Autorização duplicada não pode substituir a vigência
imutável sem erro.

No `BEGIN IMMEDIATE` da **reserva transacional**,
`despachar_registrado` verifica novamente: existência do registro,
horário de geração do próprio template, SHA editorial, limite de 24 horas,
geração não futura e relógio atual anterior ao vencimento. Uma base
legada sem vigência **não pode reservar**. Não existe parâmetro público
para escolher ou ampliar o relógio do disparo.

## Auditoria histórica versus atualidade

O preflight histórico pode retornar `PREVALIDADO_OFFLINE` para um
dossiê gerado em data anterior. Isso significa que estava coerente
no horário declarado da geração, **não** que ainda possa ser publicado.

`avaliar_pacote_offline` e `avaliar_lote_offline` agora incluem
`vigencia.estado_temporal` (`DENTRO_DO_PRAZO`, `EDICAO_FUTURA`,
`EDICAO_VENCIDA` ou `NAO_AVALIADA`) e `vigencia.valido_ate_utc`.
A CLI `scripts/nivon_preparar_pacote.py` exibe esses valores para um
dossiê ou até 200 em lote, sem ler chaves, mutar banco ou enviar nada.
O campo `envio_habilitado` permanece sempre `false`.

`diagnostico_outbox` faz a mesma separação no SQLite:
`VIGENCIA_EDITORIAL_AUSENTE`, `EDICAO_FUTURA`,
`EDICAO_VENCIDA` e `VIGENCIA_EDITORIAL_INVALIDA`.

## Provas de execução

A suíte integrada cobre:
- Preflight e persistência da publicação mais antiga por SHA de edição;
- Reservas sintéticas antes do limite e rejeição no segundo exato do vencimento;
- Rejeição de geração futura e alteração de horário do template;
- Falha fechada em banco legado sem linha em `nivon_vigencia_editorial`;
- Exibição da situação temporal em CLI e lote sem dados pessoais;
- Concorrência entre dois processos, backup/restauração, timeout e replay;
- Assinaturas de cinco emissores, revogação e opt-out global preservados.

A avaliação atual usa o relógio real do processo. **Somente os testes**
substituem a função de relógio por mocks em código de fixture para
comprovar os limites de edições históricas; isso não é controle de
produção, credencial, opção CLI nem rota de desvio.

## Restrições que seguem bloqueando operação

O campo `publicado_em` ainda depende da homologação independente da
fonte original. Sem prova externa de publicação/hora não se deve
supor que a informação é verdadeira ou atual. Também seguem pendentes
licença/direitos, consentimento institucional, autoridades reais em cofre,
aprovação de orçamento, mensageria Meta homologada, infraestrutura e
backup com restauração testada.

A janela de 24 horas é necessária, **não suficiente**, para liberar
um briefing: dados econômicos/bolsas têm seu próprio calendário e regras
de freshness, e nenhum desses registros autoriza envio automaticamente.

**Sem merge na `main`, sem deploy, agendamento, custo, coleta real ou
mensagem WhatsApp nesta etapa.**
