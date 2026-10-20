# Histórico do line-up nacional em SQLite — escopo 45 portos

`src/nivon/lineup_historico.py` consolida a proveniência de edições de line-up por **porto individual** a partir de linhas normalizadas. Cada snapshot contém uma publicação/edição identificada por SHA, data de publicação (quando fornecida pelo parser) e coletas sucessivas. As consultas por corte escolhem **a edição mais recente inteira**, evitando somar ou transportar navios de snapshots anteriores para uma programação atual.

A unidade de dado preserva situação, evidência, navio, DUV/IMO, produto, lote, toneladas programadas e toneladas realizadas, sem confundi-las. Os gates existentes de `lineup_nacional.normalizar_linha` continuam bloqueando `REALIZADO` sem evidência de movimentação oficial. O novo armazenamento não usa média de portos e não deduplica escalar navios apenas pelo nome.

Modo padrão sintético. Para dados reais exige catálogo habilitado, direitos de coleta/armazenamento, homologação do parser, endpoint e direitos comerciais **por porto**, URL de origem exata e hash SHA-256 confrontado com o arquivo original. O catálogo atual tem tudo desligado, portanto **não existe coleta operacional homologada**. Os bytes originais não são retidos pelo módulo (mas a observação de navios fica no banco privado).

Não há verificação autônoma do portal oficial ou da licença. Para PDF exige assinatura básica; para HTML exige tabela e rejeita marcadores comuns de bloqueio. Arquivos brutos e backfill retrospectivo dependem de fontes e condições de uso aprovadas. Este módulo não realiza HTTP, agendamento, merge, deploy, contratação ou publicação.
