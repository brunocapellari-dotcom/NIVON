# MDIC — ingestão anual incremental offline, memória limitada

Origem oficial: https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta

Módulo `src/nivon/mdic_stream.py`: aceita apenas arquivos anuais locais `EXP_AAAA.csv`, `IMP_AAAA.csv`, `EXP_AAAA_MUN.csv`, `IMP_AAAA_MUN.csv`. Padrão é **SEM acesso à rede**, catálogo operacional ainda desabilitado, sem armazenamento bruto no repositório. Cada modalidade verifica o cabeçalho oficial (11, 13 ou 8 colunas respectivamente), código NCM8 ou SH4, UF, mês, ano e valores.

Dois passes sequenciais limitados (primeiro SHA-256, segundo CSV em streaming), portanto arquivos superiores a 75 MB podem ser tratados sem carregar tudo na RAM, sujeitos ao limite configurado e recursos reais do host. Agregação devolve recortes para posições explicitamente solicitadas e **totais de controle por mês de todas as linhas do CSV**, inclusive posições não selecionadas. Esse total ainda não é conciliação externa: validar com planilhas de totais publicadas no MDIC para mesmo período, direções e revisões.

Na classificação municipal `CO_MUN` indica **domicílio fiscal do declarante**, não fazenda, origem logística ou carga rodoviária. URF não é porto físico e não deve substituir estatísticas ANTAQ. Custos FOB, frete e seguro internacionais de importação não são PPI do diesel nem preço nacional entregue. Ano de 1989–1996 exige parser separado NBM, não aplicar NCM.

Antes de go-live: direitos por operação, teste integral de arquivo real autorizado, conciliação externa, tabela de códigos com versões, armazenamento em nuvem e backup/restauração. Identificação do arquivo é apenas indício nominal; publicação não é inferida de competência. Nenhum agendamento, deploy ou custo ativado.
