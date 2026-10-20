# MDIC — ingestão anual incremental offline, memória limitada

Origem oficial: https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta

Módulo `src/nivon/mdic_stream.py`: aceita apenas arquivos anuais locais `EXP_AAAA.csv`, `IMP_AAAA.csv`, `EXP_AAAA_MUN.csv`, `IMP_AAAA_MUN.csv`. Padrão é **SEM acesso à rede**, catálogo operacional ainda desabilitado, sem armazenamento bruto no repositório. Cada modalidade verifica o cabeçalho oficial (11, 13 ou 8 colunas respectivamente), código NCM8 ou SH4, UF, mês, ano e valores.

Dois passes sequenciais limitados (primeiro SHA-256, segundo CSV em streaming), portanto arquivos superiores a 75 MB podem ser tratados sem carregar tudo na RAM, sujeitos ao limite configurado e recursos reais do host. Agregação devolve recortes para posições explicitamente solicitadas e **totais de controle por mês de todas as linhas do CSV**, inclusive posições não selecionadas. Esse total ainda não é conciliação externa: validar com planilhas de totais publicadas no MDIC para mesmo período, direções e revisões.

Na classificação municipal `CO_MUN` indica **domicílio fiscal do declarante**, não fazenda, origem logística ou carga rodoviária. URF não é porto físico e não deve substituir estatísticas ANTAQ. Custos FOB, frete e seguro internacionais de importação não são PPI do diesel nem preço nacional entregue. Ano de 1989–1996 exige parser separado NBM, não aplicar NCM.

Antes de go-live: direitos por operação, teste integral de arquivo real autorizado, conciliação externa, tabela de códigos com versões, armazenamento em nuvem e backup/restauração. Identificação do arquivo é apenas indício nominal; publicação não é inferida de competência. Nenhum agendamento, deploy ou custo ativado.

## Verificação pontual de cabeçalhos 2026 (19/10/2026)

Foi executada no GitHub Actions uma tentativa de ler somente os primeiros 4.096 bytes de cada um dos quatro CSVs oficiais anuais de 2026, sem armazenar linhas nem dados individuais. Todas as quatro requisições a `balanca.mdic.gov.br` retornaram `URLError`, portanto **não é possível declarar o layout real validado pelo recurso remoto**. O índice HTML do MDIC foi previamente acessado com sucesso e confirmou os links anuais, mas confirmação de link **não é acesso aos bytes**. O workflow de inspeção foi removido para não repetir a tentativa em todo PR. Os layouts dos parsers seguem baseados no esquema textual da publicação oficial e nos testes sintéticos.

## Uma passagem de leitura e hash (20/10/2026)

O código passou a ler os CSVs com `TextIOWrapper(BufferedReader)` sobre um leitor que calcula SHA-256 **sobre os mesmos bytes consumidos pelo parser**. Não há segunda leitura entre a obtenção do hash e os cálculos. O arquivo é aberto sem seguir link simbólico quando o SO disponibiliza `O_NOFOLLOW`, e são comparados tamanho, dispositivo, inode, mtime e ctime antes e depois do processamento, incluindo a quantidade efetivamente lida. Isso reduz riscos de inconsistência entre hash e valores diante de alterações concorrentes; não substitui controle de acesso ao diretório e não comprova a origem oficial do CSV. Testes incluem BOM UTF-8/CRLF e hashes byte a byte.
