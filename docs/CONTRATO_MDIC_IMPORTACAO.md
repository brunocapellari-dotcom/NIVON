# MDIC Comex Stat - Importação NCM (OFFLINE)

Fonte oficial: https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta

CSV importação com 13 colunas: CO_ANO;CO_MES;CO_NCM;CO_UNID;CO_PAIS;SG_UF_NCM;CO_VIA;CO_URF;QT_ESTAT;KG_LIQUIDO;VL_FOB;VL_FRETE;VL_SEGURO.

Parser local src/nivon/mdic_importacao.py separa valores FOB, frete e seguro internacionais e calcula CIF aritmético sem transformar o resultado em preço nacional. Preserva período, NCM, UF, país, via e URF; não determina município nem rota física. NCMs devem ter vigência por período em dicionário separado.

Pendências: testes de amostra real, totais publicados MDIC, direitos por operação, backfill e armazenamento com restore. Não ativa rede, agendamento ou publicação.
