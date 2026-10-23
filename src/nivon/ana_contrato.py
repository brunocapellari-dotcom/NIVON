"""Plano offline da nova ANA HidroWebService. Acesso SSO é condição externa.

Não usa SOAP legado, não faz requisições e não inventa parâmetros de API.
Segundo Swagger ANA: telemetria até 30 dias; convencional/HidroSat até 366.
"""
from __future__ import annotations
import re
from datetime import date, timedelta

DOCS="https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html"
FAMILIAS={
    "TELEMETRIA_ADOTADA":("HidroinfoanaSerieTelemetricaAdotada",30),
    "TELEMETRIA_DETALHADA":("HidroinfoanaSerieTelemetricaDetalhada",30),
    "CONVENCIONAL_COTAS":("HidroSerieCotas",366),
    "CONVENCIONAL_VAZAO":("HidroSerieVazao",366),
    "CONVENCIONAL_CHUVA":("HidroSerieChuva",366),
    "SATELITE_HIDROSAT":("HidrosatSerieDados",366),
}
class ErroContratoANA(ValueError):
    pass

def planejar_janelas(*,estacao_id:str,data_inicio:str,data_fim:str,familia:str)->dict:
    if familia not in FAMILIAS:
        raise ErroContratoANA("família desconhecida; SOAP legado não autorizado")
    if not isinstance(estacao_id,str) or not re.fullmatch(r"[0-9]{6,10}",estacao_id):
        raise ErroContratoANA("estação ANA requer código numérico explícito")
    try:
        inicio=date.fromisoformat(data_inicio);fim=date.fromisoformat(data_fim)
    except (ValueError,TypeError) as exc:
        raise ErroContratoANA("datas YYYY-MM-DD obrigatórias") from exc
    if fim<inicio or (fim-inicio).days>36525:
        raise ErroContratoANA("intervalo vazio ou excessivo")
    endpoint,limite=FAMILIAS[familia];cursor=inicio;janelas=[]
    while cursor<=fim:
        fim_janela=min(fim,cursor+timedelta(days=limite-1))
        janelas.append({"inicio":cursor.isoformat(),"fim":fim_janela.isoformat(),
                        "dias":(fim_janela-cursor).days+1})
        cursor=fim_janela+timedelta(days=1)
    return {"dataset_id":"ANA_HIDRO","estacao_id":estacao_id,"familia":familia,
            "endpoint_documentado":f"/EstacoesTelemetricas/{endpoint}/v1",
            "documentacao":DOCS,"autenticacao":"SSO_REQUER_ACESSO_DA_ANA",
            "parametros_request":"AGUARDA_TUTORIAL_TOKEN_E_HOMOLOGACAO",
            "dias_por_requisicao_max":limite,"janelas":janelas,
            "executar":False,"direitos_coleta_confirmados":False,
            "nota":"API antiga com prazo de descontinuação em 2026; sem fallback."}
