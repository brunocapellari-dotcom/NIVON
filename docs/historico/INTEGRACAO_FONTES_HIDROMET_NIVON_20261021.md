# NIVON — Registro operacional de APIs meteorológicas e hidrológicas
**Verificado/documentado em:** 21/10/2026. **Finalidade:** uso não comercial.  
**Princípio:** dados observados de estações, grades/reanálises e previsões são produtos diferentes, jamais intercambiáveis. O runtime só acessa rede sob opt-in.

## Matriz de integração

| Fonte | O que pode alimentar | Contrato NIVON | Situação de comprovação |
| --- | --- | --- | --- |
| INMET catálogo oficial | Cadastro, código, latitude/longitude e situação da estação | src/nivon/inmet_estacoes_publicas.py (PR #87) | Código/testes offline; endpoint público consultado externamente; sem série medida |
| INMET histórico anual oficial | Chuva, temperatura e vento por estação, séries observadas | src/nivon/inmet_historico.py (main), inspeção ZIP | Parser/índice offline; arquivos reais não carregados; BDMEP privado expirou |
| CPTEC/INPE via BrasilAPI | Previsão local até 6 dias | src/nivon/cptec_previsao_brasilapi.py (PR #87) | Testes offline; API upstream não homologada ao vivo |
| ANA HidroWebService | Estações telemétricas: chuva, cota, vazão | src/nivon/ana_hidrowebservice.py (main) | **Autenticação LIVE confirmada** Actions #39666762333; leitura real pendente de estação/data/fuso |
| NASA POWER Daily AG | Histórico de chuva, temperaturas, vento, radiação: grade satélite/modelo | src/nivon/hidromet_publico_global.py | Novo conector; testes offline; sem homologação LIVE |
| Open-Meteo Forecast | Previsão diária de chuva e temperatura | src/nivon/hidromet_publico_global.py | Novo conector; testes offline; sem homologação LIVE |
| Open-Meteo Archive | Reanálise histórica diária, dados interpolados/modelados | src/nivon/hidromet_publico_global.py | Novo conector; testes offline; sem homologação LIVE |
| Copernicus GloFAS via Open-Meteo | Vazão fluvial prevista **simulada** em m³/s | src/nivon/hidromet_publico_global.py | Novo conector; testes offline; não converter diretamente em nível navegável |
| CEMADEN PED (JWT) | Chuva acumulada recente por município/estação, observação bruta | src/nivon/cemaden_ped.py | Novo conector e testes offline; **precisa acesso/token CEMADEN autorizado** |
| SGB SACE | Cotas observadas, alertas e boletins hidrológicos | https://www.sgb.gov.br/sace/ | **CATÁLOGO**: não há contrato JSON API comprovado para integração direta |
| NOAA/CPC e CPTEC sazonal | Índices climáticos e previsões probabilísticas de médio prazo | Inventário/contratos ainda em branches meteorológicos | **PENDENTE de reconciliação**; não repetir coletores existentes |

## Links primários e licenças a revisar

- ANA Swagger: https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html
- CPTEC XML: https://servicos.cptec.inpe.br/XML/
- Portal CPTEC: https://www2.cptec.inpe.br/ — uso não comercial com atribuição CPTEC/INPE e restrições de reprodução
- INMET histórico: https://portal.inmet.gov.br/dadoshistoricos/
- NASA POWER: https://power.larc.nasa.gov/docs/services/api/temporal/daily/ — resolução da grade e limites de requisições
- NASA parâmetros: https://power.larc.nasa.gov/parameters/
- Open-Meteo: https://open-meteo.com/en/docs — uso não comercial gratuito condicionado a fair use/atribuição
- Copernicus GloFAS: https://open-meteo.com/en/docs/flood-api — resolução ~5 km, curso fluvial mais próximo pode divergir
- CEMADEN PED Swagger: https://sws.cemaden.gov.br/PED/api/ui/swagger.json — cada consulta exige cabeçalho `token`, JWT; sistema de tokens: https://sgaa.cemaden.gov.br/SGAA/api/ui/
- SGB SACE: https://www.sgb.gov.br/sace/ — monitoramento/alerta, mas não há API pública JSON homologada neste ciclo

## Utilização dos conectores: leitura pontual, sem automação

```bash
PYTHONPATH=src python -m nivon.hidromet_pontual_cli --fonte nasa_power --latitude -12.5 --longitude -55.7 --inicio 2026-10-01 --fim 2026-10-02
# Retorna REDE_DESATIVADA. Acrescentar --live para exatamente 1 GET público.
PYTHONPATH=src python -m nivon.hidromet_pontual_cli --fonte openmeteo --latitude -12.5 --longitude -55.7 --dias 3 --live
PYTHONPATH=src python -m nivon.hidromet_pontual_cli --fonte glofas --latitude -12.5 --longitude -55.7 --dias 3 --live
```

O CLI informa somente resultado de validação técnica, contagem de registros e flags fail-closed. Nunca imprime séries/URLs privadas. CEMADEN usa o segredo de ambiente `NIVON_CEMADEN_TOKEN` (não provisionado). Um resultado de leitura não muda `homologado=false`, `coleta_agendada=false` e `publicavel=false`.

## Gates pendentes para ligar ao banco e relatórios

1. Teste LIVE pontual com API real; comparar campos, datas, timezone, unidades, exceções e limites do contrato (nem sucesso em mock nem HTTP 200 bastam).
2. Auditoria de licença, atribuição, cache/redistribuição e retenção por provedor; não presumir que a condição não comercial autoriza reprodução irrestrita.
3. Armazenamento raw permitido (checksum, URL sanitizada, data_referencia, data_publicacao, data_coleta, competencia), granularidade temporal e deduplicação de cada fonte.
4. Dados observados de INMET/ANA/CEMADEN com QC, fuso, origem e riscos de estação; grades NASA e Open-Meteo como modelagem/reanálise; GloFAS como previsão hidrológica.
5. Calibração GloFAS com ANA para rios e trechos relevantes; não apresentar previsão de vazão como profundidade navegável/cota real nem afirmar rota operacional.
6. Sem cadência de coleta automática, despliegue Vercel, projeto GCP ou aumento de custos sem autorização. Branchs ainda não integradas à `main` não constituem serviço em produção.

## Próxima ação específica que depende do titular

Para **CEMADEN**, providenciar acesso legítimo e configurar `NIVON_CEMADEN_TOKEN` no ambiente privado autorizado; não registrar JWT no repositório nem em respostas. Para **ANA**, escolher estação canônica, data e timezone para primeira leitura real, após validar mapeamento HIDRO/IBGE. Os conectores públicos não exigem credenciais do titular, apenas teste de rede controlado.


## Provas de rede executadas em 21/10/2026 (GitHub Actions)

Execuções pontuais com saída sanitizada, sem download persistente, secrets ou agendamento:

- [Run #39673211755](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39673211755): NASA POWER (2 dias), Open-Meteo previsão (3 dias), Open-Meteo reanálise (2 dias) e GloFAS (3 dias) retornaram JSON normalizado pelo conector. Estado `RESPOSTA_RECEBIDA_SEM_HOMOLOGACAO`; não equivale a aprovação de licença, qualidade/frescor ou ingestão de dados.
- No mesmo run, INMET catálogo e CPTEC via BrasilAPI foram `CONSULTA_NAO_VALIDADA`, sem indicar causa.
- [Run #39673500223](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39673500223): diagnóstico público sanitizado restrito a dois endpoints. **INMET = TRANSPORTE_NAO_VALIDADO** no GitHub runner; não há prova de indisponibilidade global, visto que o endpoint de estações respondeu em consulta pública externa. **BrasilAPI CPTEC = HTTP 403**. Não repetir/contornar bloqueio por scraping; investigar acesso oficial e alternativas autorizadas.
- [Run #39673211660](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39673211660): 88 testes offline passaram na branch consolidada antes do workflow diagnóstico. O estado final da branch deve ser validado novamente antes do merge.
- **CEMADEN:** apenas simulação, exige JWT e autorização via SGAA. Sem consulta live.
- **ANA:** a autenticação já havia sido confirmada, mas série hidrológica real por estação e data ainda não foi coletada.

Não publicar relatórios meteorológicos ou hidrológicos a partir de séries sem QC, sem revisão da licença e sem registro de competência/vintages. As duas respostas não validadas não afetam a leitura real das outras fontes.
