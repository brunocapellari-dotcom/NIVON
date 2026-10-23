# NIVON — Cadeia hidrológica da chuva ao fluxo de rio

**Versão:** 20 de outubro de 2026 · **PR #1** · **Status:** motor físico determinístico testado offline; sem previsão hidrológica calibrada.

## Equações canônicas e fontes

**USDA NRCS, NEH-630 Cap. 10 — SCS Curve Number:** https://directives.nrcs.usda.gov/sites/default/files2/1712930608/7300.pdf

- `S = 25400/CN - 254` mm; `Ia=lambda*S`; `Q = (P-Ia)^2/(P+(1-lambda)*S)` quando `P>Ia`, zero caso contrário.
- `1 mm * 1 km² = 1000 m³`. O volume derivado é escoamento direto POTENCIAL em um evento de chuva de área/bacia conhecida.
- `CN` depende de classe de solo, uso do solo, manejo, condições anteriores e treinamento. Não inferir CN da temperatura. Exigir `lambda` explícito: 0,2 apenas como hipótese NRCS clássica.
- Não inferir vazão fluvial ou condição de navegação diretamente de `Q` sem propagação, geometria da bacia e verificação de observações.

**USACE HEC-HMS Muskingum:** https://www.hec.usace.army.mil/confluence/hmsdocs/hmstrm/channel-flow/muskingum-model

- `O(t) = C0*I(t) + C1*I(t-1) + C2*O(t-1)`.
- `C0=(dt-2*K*X)/(2*K*(1-X)+dt)`; `C1=(dt+2*K*X)/(2*K*(1-X)+dt)`; `C2=(2*K*(1-X)-dt)/(2*K*(1-X)+dt)`.
- `K`: horas de propagação do trecho; `X`: 0 a 0,5; intervalo `dt` definido no contrato. Bloquear parâmetros quando `dt < 2KX` ou `dt > 2K(1-X)`, pois podem produzir coeficientes negativos e instabilidade.
- Calcular armazenamento modelado `S(t) = K*[X*I(t)+(1-X)*O(t)]*3600` m³; auditar `deltaS = (I_ant+I_atual-O_ant-O_atual)*dt*3600/2`.
- Data/hora da vazão com timezone e passo uniforme; séries com lacunas ou inversão de calendário são rejeitadas.
- `O(t)` ainda é **fluxo estimado**, não medições em rios sem bacias georreferenciadas, afluentes laterais e calibração.

## Motores na plataforma

- `src/nivon/hidrologia_chuva_vazao.py`: `escoamento_scs_cn`, `propagar_muskingum`.
- `src/nivon/motores_hidrologia_cientifica.py`: curva-chave por estação, balanço de reservatórios e métricas NSE.
- `src/nivon/motores_meteo_hidro.py`: nível, vazão e triagem de calado hipotético.
- `src/nivon/validacao_previsoes_ambientais.py`: corta dados posteriores à emissão e exige baseline/horizonte/QC.
- `config/motores_inteligencia.v1.json`: motores ligados a HIDROLOGIA e CLIMA_HIDRO, mantidos desligados para operação.

## Próximas etapas até inteligência preditiva real

1. Selecionar bacias prioritárias de Mato Grosso (Rio Teles Pires, Tapajós, Juruena, Madeira, Paraguai etc.), afluentes e estações ANA por código.
2. Obter dados reais autorizados do HidroWebService e chuvas correspondentes (INMET, CHIRPS/IMERG), respeitando vintages e qualidade.
3. Calibrar CN/lag K/X por bacia/trecho usando séries históricas pareadas, considerar solo/cobertura e reanálise de precipitação.
4. Realizar validação por bacias/anos não utilizados no treino, incluindo períodos extremos e métricas contra baseline e intervalos de incerteza.
5. Para navegação, somar batimetria, datum, autoridade, calado, eventos de dragagem e remanso; **não declarar navegação segura com base apenas na vazão simulada**.

Nenhum monitoramento contínuo, alerta de cheia/estiagem ou decisão operacional decorre destes testes sintéticos.
