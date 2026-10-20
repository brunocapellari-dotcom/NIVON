# ANP — descobridor de arquivos mensais de diesel/GNV

O portal oficial de dados abertos da ANP reúne (a) arquivos mensais de registros de revenda de diesel e GNV a partir dos anos mais recentes e (b) uma série **agregada semanal por município desde 2004**, com metodologia e layouts distintos. Referências:
- https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis
- https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/serie-historica-do-levantamento-de-precos

`anp_manifesto.py` extrai offline os links realmente publicados em 1 ou mais páginas da listagem anual `/shpc/dsan/ANO`. O índice possui paginação e nomes de arquivo inconsistentes; **não** inventar links com templates nem declarar mês ausente como zero. O módulo exige meses explícitos e saída marca `meses_sem_link`.

Para ingestão, os arquivos atuais de revenda mensal têm dados cadastrais de postos: não commitar, logar, publicar ou armazenar CNPJ/razão/endereço. O normalizador existente `anp_diesel.py` gera somente preços amostrais municipais/semanais inferidos, e não diesel A no produtor nem PPI internacional.

O histórico semanal publicado pela ANP tem janela longa e preços agregados próprios; exige parser por layout/ciclo, não deve ser fundido com a série derivada de CSV bruto sem validação de metodologia. Revisar direitos por operação, edição histórica, testes reais, reconciliação, persistência durável e restore antes de ativar coletas automáticas. Custo adicional ou deploy não autorizado.
