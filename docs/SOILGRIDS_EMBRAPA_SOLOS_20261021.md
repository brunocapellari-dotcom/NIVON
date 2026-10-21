# NIVON — fontes abertas de solo: ISRIC SoilGrids e Embrapa GeoInfo (21/10/2026)

## Integração implementada

- **ISRIC SoilGrids**: REST GET `https://rest.isric.org/soilgrids/v2.0/properties/query`, consulta pontual de pH, argila, areia, silte, carbono orgânico, N, densidade e CTC, em seis profundidades. Python 3.11, sem chave, uma requisição HTTPS por acionamento explícito, limite 300KB, timeout, HTTPS, bloqueio de redirect, hash e timezone. Normaliza o fator `unit_measure.d_factor` para unidade física e preserva valor bruto. **Dados modelados 250m**, não amostra de laboratório ou recomendação agronômica.
- **Embrapa GeoInfo**: fonte e dataset cadastrados no Catálogo Mestre, acesso estruturado público por GeoJSON, SHP e WFS, inclusive mapa de solos nacional e mapa de água disponível. Esquema, licença e identificador WFS específicos precisam de teste antes de construir o parser; nenhuma coleta da Embrapa foi declarada ativa.

## Licença e confiabilidade

ISRIC SoilGrids é CC BY 4.0, exige atribuição. REST v2 em beta sem garantia de disponibilidade, política de uso justo de no máximo 5 requisições/minuto. Para extração em escala, preferir WCS/WebDAV em vez de consultar ponto a ponto em loop. GeoInfo Embrapa é aberto/gratuito, mas cada camada deve ser analisada; mapa nacional escala 1:5.000.000 não valida precisão em talhões.

## Testes

`tests/test_isric_soilgrids.py` cobre normalização de unidade (pH bruto 58 / fator 10 = 5,8), limites geográficos, HTTPS, bloqueio padrão, dados inválidos e separação de dado modelado e amostra.

## Pendências

Não foram efetuadas consultas HTTP reais, instalação, agendamento ou armazenamento durável nesta integração. Direitos por operação, teste real, quota e publicação seguem bloqueados no catálogo central. Não construir ou recomendar qualquer motor de receituário agronômico.

Fontes: https://rest.isric.org/ ; https://rest.isric.org/soilgrids/v2.0/docs ; https://docs.isric.org/globaldata/soilgrids/index.html ; https://www.gov.br/pt-br/servicos/consultar-informacoes-geoespaciais-na-plataforma-geoinfo ; https://geoinfo.dados.embrapa.br/
