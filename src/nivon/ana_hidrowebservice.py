"""ANA HidroWebService 2026: cliente HTTP de leitura explícita e autenticação SSO.

Implementação do manual oficial, versão 20/02/2026. Nenhuma credencial
é importada do Gmail ou armazenada em código. Sem rede ao importar módulos.
O chamador opta explicitamente por solicitar token (timeout/host fixos);
não persiste o token nem inclui credenciais em URLs ou logs.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = "https://www.ana.gov.br/hidrowebservice/EstacoesTelemetricas"
LOGIN = BASE + "/OAUth/v1"
MANUAL = "https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf/@@download/file"
_EST = re.compile(r"[0-9]{6,10}\Z")
_STATUS = {"0":"APROVADO", "1":"SUSPEITO", "2":"RUIM"}
_METRICAS = {
    "Chuva_Adotada": ("CHUVA_INTERVALO_MM","MM"),
    "Cota_Adotada": ("COTA_CM","CM"),
    "Vazao_Adotada": ("VAZAO_M3_S","M3_S"),
}

class ErroANAAPI(ValueError):
    pass

class _SemRedirecionamentos(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def credenciais_ambiente():
    """Nunca retorna valores em diagnóstico, nunca aceita default no código."""
    user = os.environ.get("NIVON_ANA_IDENTIFICADOR", "")
    password = os.environ.get("NIVON_ANA_SENHA", "")
    if not user.isdecimal() or len(user) not in (11,14) or not password or "\n" in password or "\r" in password:
        raise ErroANAAPI("credenciais ANA não configuradas em secret vault/ambiente")
    return user,password

def construir_login(*,identificador:str,senha:str)->Request:
    if not isinstance(identificador,str) or not identificador.isdecimal() or len(identificador) not in (11,14):
        raise ErroANAAPI("identificador inválido")
    if not isinstance(senha,str) or not senha or any(x in senha for x in ("\r","\n")):
        raise ErroANAAPI("senha inválida")
    # A documentação ANA (20/02/2026) requer header, NÃO query string.
    return Request(LOGIN,method="GET",headers={
        "Identificador":identificador, "Senha":senha, "Accept":"application/json",
    })

def _json_api(payload:bytes,*,limite_bytes=2_000_000)->dict:
    if not isinstance(payload,bytes) or not 1<=len(payload)<=limite_bytes:
        raise ErroANAAPI("resposta fora dos limites")
    def pares_distintos(pairs):
        obj={}
        for key,value in pairs:
            if key in obj:raise ErroANAAPI("resposta JSON com chave duplicada")
            obj[key]=value
        return obj
    try:
        obj=json.loads(payload.decode("utf-8-sig"),object_pairs_hook=pares_distintos)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ErroANAAPI("resposta não é JSON válido") from exc
    if not isinstance(obj,dict) or obj.get("code")!=200 or obj.get("status")!="OK":
        raise ErroANAAPI("ANA não confirmou sucesso HTTP/lógico")
    return obj

def extrair_token(payload:bytes)->str:
    obj=_json_api(payload,limite_bytes=32_768)
    items=obj.get("items")
    if not isinstance(items,dict):
        raise ErroANAAPI("ANA não retornou estrutura do token")
    token=items.get("tokenautenticacao")
    if not isinstance(token,str) or not 20<=len(token)<=8192 or any(c in token for c in ("\r","\n"," ")):
        raise ErroANAAPI("token SSO ausente ou inválido")
    return token

@dataclass(repr=False)
class SessaoANA:
    token:str
    emitido_monotonic:float
    duracao_max_segundos:int=3300  # margem de 5 minutos do prazo oficial de 60m

    def _ativo(self,agora_monotonic:float)->str:
        if not isinstance(agora_monotonic,(int,float)) or agora_monotonic<self.emitido_monotonic or agora_monotonic-self.emitido_monotonic>=self.duracao_max_segundos:
            raise ErroANAAPI("token expirado ou tempo do relógio incompatível")
        return self.token

def construir_consulta_adotada(*,estacao:str,token:str,data_busca:str,
                             intervalo:str="HORA_1")->Request:
    if not isinstance(estacao,str) or not _EST.fullmatch(estacao):
        raise ErroANAAPI("estação ANA inválida")
    try:datetime.strptime(data_busca,"%Y-%m-%d")
    except (ValueError,TypeError) as exc:raise ErroANAAPI("data de busca inválida") from exc
    # Manual oficial: DataDaBusca + TipoFiltroData + RangeIntervaloDeBusca
    if intervalo not in {"MINUTO_5","MINUTO_10","MINUTO_15","MINUTO_30","HORA_1","HORA_2","HORA_3","HORA_4","HORA_6","HORA_12","HORA_24"}:
        raise ErroANAAPI("intervalo não autorizado no adaptador")
    if not isinstance(token,str) or len(token)<20 or "\r" in token or "\n" in token:
        raise ErroANAAPI("bearer não fornecido")
    from urllib.parse import urlencode
    params=urlencode({"CodigoDaEstacao":estacao,"TipoFiltroData":"DATA_LEITURA",
                      "DataDaBusca":data_busca,"RangeIntervaloDeBusca":intervalo})
    return Request(BASE+"/HidroinfoanaSerieTelemetricaAdotada/v1?"+params,
        headers={"Authorization":"Bearer "+token,"Accept":"application/json"},method="GET")

def efetuar_request(request:Request,*,habilitar_rede:bool=False,timeout=12,
                    transporte=None,limite_bytes=2_000_000)->bytes:
    """Rede só com habilitação explícita. Transporte injetável para testes."""
    if not habilitar_rede:
        raise PermissionError("rede ANA exige habilitação explícita pelo executor autorizado")
    if request.full_url.split("?")[0] not in (
        LOGIN,BASE+"/HidroinfoanaSerieTelemetricaAdotada/v1"
    ) or request.get_method()!="GET":
        raise ErroANAAPI("request fora de endpoint oficial permitido")
    if type(timeout) not in (float,int) or not 1<=timeout<=30:
        raise ErroANAAPI("timeout inválido")
    opener=transporte or build_opener(_SemRedirecionamentos)
    try:
        with opener.open(request,timeout=timeout) as resp:
            if getattr(resp,"status",None)!=200:
                raise ErroANAAPI("resposta de API diferente de 200")
            data=resp.read(limite_bytes+1)
    except ErroANAAPI:
        raise
    except Exception as exc:
        # Não incluir request, headers, token, senha ou corpo do erro.
        raise ErroANAAPI("falha de acesso à API ANA; conferir acesso autorizado") from None
    if len(data)>limite_bytes:
        raise ErroANAAPI("resposta ANA excede tamanho máximo")
    return data

def _parse_local(value, *, source_zone):
    """API ANA transmite timestamps sem offset: zona da ESTAÇÃO precisa ser explícita."""
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    if source_zone not in ("America/Manaus","America/Sao_Paulo","America/Cuiaba",
                          "America/Belem","America/Rio_Branco","America/Porto_Velho",
                          "UTC"):
        raise ErroANAAPI("zona de medição não aprovada para estação")
    try:
        tz=ZoneInfo(source_zone)
        d=datetime.fromisoformat(value.replace(" ","T"))
    except (ValueError,AttributeError,ZoneInfoNotFoundError) as exc:
        raise ErroANAAPI("Data_Hora_Medicao inválida") from exc
    if d.tzinfo is not None:
        raise ErroANAAPI("medição com fuso inesperado no contrato ANA")
    return d.replace(tzinfo=tz).astimezone(timezone.utc).isoformat()

def normalizar_adotada(payload:bytes,*,estacao:str,zona_estacao:str,
                      coletado_em:str,origem_sha256:str)->list[dict]:
    """Preserva medições instantâneas: chuva 5/60 minutos NÃO é chuva diária."""
    if not isinstance(estacao,str) or not _EST.fullmatch(estacao):
        raise ErroANAAPI("estação ANA inválida")
    if not re.fullmatch(r"[0-9a-f]{64}",origem_sha256):
        raise ErroANAAPI("SHA-256 inválido")
    try:
        coleta=datetime.fromisoformat(coletado_em.replace("Z","+00:00"))
    except (ValueError,AttributeError) as exc:
        raise ErroANAAPI("coleta com data inválida") from exc
    if coleta.tzinfo is None or coleta.utcoffset() is None:
        raise ErroANAAPI("coleta requer fuso")
    obj=_json_api(payload)
    entries=obj.get("items")
    if not isinstance(entries,list) or len(entries)>10000:
        raise ErroANAAPI("lista de medições inválida")
    output=[];ident=set()
    for item in entries:
        if not isinstance(item,dict) or str(item.get("codigoestacao",""))!=estacao:
            raise ErroANAAPI("código da estação divergente")
        when=_parse_local(item.get("Data_Hora_Medicao"),source_zone=zona_estacao)
        for key,(metric,unit) in _METRICAS.items():
            raw=item.get(key)
            qc=item.get(key+"_Status")
            if raw is None and qc is None:continue
            if qc is None or str(qc) not in _STATUS:
                raise ErroANAAPI("código QC ausente/desconhecido")
            if raw is None or raw in ("","null","-"):
                continue
            try:
                from decimal import Decimal, InvalidOperation
                val=float(Decimal(str(raw)))
            except (ValueError,InvalidOperation,TypeError) as exc:
                raise ErroANAAPI("medição numérica inválida") from exc
            from math import isfinite
            if not isfinite(val) or (metric!="COTA_CM" and val<0):
                raise ErroANAAPI("medição não finita ou fisicamente inválida")
            identkey=(estacao,when,metric)
            if identkey in ident:raise ErroANAAPI("medição duplicada na versão")
            ident.add(identkey)
            output.append({"dataset_id":"ANA_HIDRO","estacao_id":estacao,
                "data_hora_medicao_utc":when,"variavel":metric,"unidade":unit,
                "valor":val,"qualidade":_STATUS[str(qc)],
                "utilizar_para_modelo":str(qc)=="0",
                "referencia":when,"publicacao":None,"coleta":coleta.astimezone(timezone.utc).isoformat(),
                "origem_sha256":origem_sha256,"natureza":"OBSERVADO",
                "nota":"QC ruim/suspeito nunca é aprovado automaticamente; chuva de intervalo não é acumulado diário"})
    return sorted(output,key=lambda r:(r["data_hora_medicao_utc"],r["variavel"]))
