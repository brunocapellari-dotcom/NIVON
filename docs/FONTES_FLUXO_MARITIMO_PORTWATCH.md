## P1 — FMI PortWatch (integração estruturada)

Cliente `src/nivon/portwatch_fluxos.py` para a tabela ArcGIS
`Daily_Chokepoints_Data/FeatureServer/0/query` (FMI PortWatch).
Metadados da API verificados em 22/10/2026; campos oficiais:
`date, portid, portname, n_total, capacity, n_dry_bulk, n_tanker`.

Permite consulta de até 31 dias por vez para passagens cadastradas:
Hormuz, Bab el-Mandeb, Suez, Panamá, Malaca e Cabo da Boa Esperança.
Rede desligada por padrão, paginação com limites e nenhuma dependência
externa. Versões de cada dia preservadas em SQLite.

**Semântica obrigatória:** `n_total` é contagem de cruzamentos AIS segundo
a metodologia PortWatch. `capacity` é proxy de toneladas de carga em trânsito estimadas por AIS e calado,
NÃO carga realizada confirmada, desembaraço aduaneiro ou line-up de porto. Datas da
medição não são intercambiáveis com data de coleta.

O portal é de acesso público, mas não foi concluída homologação das
condições para coleta automatizada em escala. Não realizar bulk download
irrestrito. A coleta incremental automatizada depende de validação
operacional e banco persistente fora do runner efêmero.

Referências:
- https://portwatch.imf.org/
- https://portwatch.imf.org/pages/data-and-methodology
- https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0?f=pjson
- https://worldbank.github.io/alternative-data-for-crisis/notebooks/disruptions-business-trade/chokepoints-monitor.html

Panamá também fornece API própria mediante cadastro de aplicação, token
OpenID Connect e autenticação: https://developer.pancanal.com/.
Essa API não deve ser representada como acesso sem credencial.

**Auditoria metodológica (FMI WP/25/93):** o campo `capacity` da série de passagens é **volume de carga em trânsito estimado (t)** pelo FMI; não é simplesmente DWT total nem carga oficialmente certificada. Campo canônico: `volume_transito_estimado_t`, classificação `ESTIMADO_MODELO_FMI`. A coluna SQL `capacidade_proxy` permanece por compatibilidade, mas armazena proxy em toneladas de carga em trânsito. Referência: https://www.imf.org/en/-/media/files/publications/wp/2025/english/wpiea2025093-print-pdf.pdf
