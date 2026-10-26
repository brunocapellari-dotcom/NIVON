"""Fatia operacional de pré-go-live: PTAX USD do BCB, somente leitura.

Consultas reais usam apenas o endpoint oficial gerado pelo planejador. O
resultado é um sinal interno com hora, idade e estado explícitos, sem
armazenamento, coleta agendada, WhatsApp, publicação ou instalação externa.
Não sobrepõe a governança de datasets: não há aprovação de coleta persistente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .bcb_ptax import ErroPTAX, normalizar_ptax_odata
from .ptax_plano import ErroPlanoPTAX, planejar_consultas_ptax

SP = ZoneInfo("America/Sao_Paulo")
MAX_BYTES = 256_000
MAX_DAYS = 10
STALE_HOURS = 96

class ErroPiloto(RuntimeError):
    """Consulta não confiável ou evidência insuficiente. Não publicar."""


class _SemRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, message, headers, target):
        raise ErroPiloto("resposta HTTP com redirecionamento não autorizado")


def obter_json_oficial(url: str) -> bytes:
    """GET somente PTAX gerada pelo planejador; não aceita URL arbitrária."""
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "olinda.bcb.gov.br"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.fragment or not parsed.path.startswith(
                "/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(")):
        raise ErroPiloto("endpoint BCB não autorizado")
    headers = {"Accept":"application/json", "User-Agent":"NIVON-MVP-interior/0.1"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        client = urllib.request.build_opener(_SemRedirect())
        with client.open(req, timeout=12) as res:
            if res.status != 200 or res.geturl() != url:
                raise ErroPiloto("status/url BCB divergente")
            mime = res.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in {"application/json", "application/json;odata.metadata=minimal"}:
                raise ErroPiloto("MIME BCB não é JSON")
            payload = res.read(MAX_BYTES+1)
    except ErroPiloto:
        raise
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as exc:
        raise ErroPiloto("BCB indisponível na consulta read-only") from exc
    if not payload or len(payload)>MAX_BYTES:
        raise ErroPiloto("resposta BCB vazia/grande demais")
    return payload


def _sem_duplicatas(pairs):
    out = {}
    for k,v in pairs:
        if k in out:
            raise ErroPiloto("JSON duplicado na resposta BCB")
        out[k] = v
    return out


def executar(*, agora: datetime, buscar=obter_json_oficial,
             dias: int=MAX_DAYS) -> dict:
    """Consultar intervalo recente e interpretar cotação, sem alteração de estado."""
    if not isinstance(agora, datetime) or agora.tzinfo is None or agora.utcoffset() is None:
        raise ErroPiloto("instante atual deve ter fuso horário")
    if type(dias) is not int or dias<3 or dias>MAX_DAYS:
        raise ErroPiloto("janela de dias fora do limite")
    current=agora.astimezone(timezone.utc)
    brasil=agora.astimezone(SP)
    fim=brasil.date()
    inicio=fim-timedelta(days=dias-1)
    try:
        plans=planejar_consultas_ptax(moeda="USD", inicio=inicio.isoformat(),
                                    fim=fim.isoformat(), dias_janela=dias)
        if len(plans)!=1:
            raise ErroPiloto("plano BCB não contido em uma consulta")
        url=plans[0]["url"]
        raw=buscar(url)
        if not isinstance(raw, bytes) or not 0<len(raw)<=MAX_BYTES:
            raise ErroPiloto("resposta BCB precisa ser bytes JSON limitados")
        data=json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_sem_duplicatas)
        norm=normalizar_ptax_odata(data, moeda="USD",
                                  coletado_em=current.isoformat(),
                                  consulta_url=url)
    except (ErroPlanoPTAX, ErroPTAX, TypeError, ValueError, UnicodeError, KeyError) as exc:
        raise ErroPiloto("dados do BCB reprovados na normalização") from exc
    observations=norm["observacoes"]
    elegiveis=[]
    for obs in observations:
        when=datetime.fromisoformat(obs["referencia_data_hora_utc"])
        if when>current:
            raise ErroPiloto("BCB informa data de observação futura")
        if obs["competencia"]<inicio.isoformat() or obs["competencia"]>fim.isoformat():
            raise ErroPiloto("BCB retornou observação fora da janela")
        elegiveis.append((when,obs))
    if not elegiveis:
        raise ErroPiloto("janela BCB sem boletim válido")
    elegiveis.sort(key=lambda x:x[0])
    latest=elegiveis[-1][1]
    age=(current-elegiveis[-1][0]).total_seconds()/3600
    if age<0:
        raise ErroPiloto("idade negativa da observação")
    # Sem valor anterior não inventar tendência nem variação.
    older=[item for when,item in elegiveis[:-1] if item["competencia"]<latest["competencia"]]
    prev=older[-1] if older else None
    delta=(100*(latest["cotacao_venda_brl_por_moeda"]/prev["cotacao_venda_brl_por_moeda"]-1)
           if prev else None)
    good=age<=STALE_HOURS
    return {
        "schema":"NIVON_PTAX_USD_READONLY_MVP_V1",
        "status":"PREVIA_INTERNA_VALIDA" if good else "INDISPONIVEL_FRESCURA",
        "fonte":"Banco Central do Brasil — PTAX/OData",
        "moeda":"USD","unidade":"BRL_por_USD",
        "coletado_utc":current.isoformat(),
        "competencia":latest["competencia"],
        "referencia_utc":latest["referencia_data_hora_utc"],
        "idade_horas":round(age,2),
        "cotacao_compra":latest["cotacao_compra_brl_por_moeda"] if good else None,
        "cotacao_venda":latest["cotacao_venda_brl_por_moeda"] if good else None,
        "variacao_venda_pct_vs_dia_anterior_observado":(
            round(delta,4) if good and delta is not None else None),
        "observacoes_no_recorte":len(elegiveis),
        "ultimo_valor_anterior_disponivel":prev is not None,
        "url_oficial":url,
        "sha256_resposta_efemera":hashlib.sha256(raw).hexdigest(),
        "dados_coletados_nao_persistidos":True,
        "consulta_ao_vivo_executada":buscar is obter_json_oficial,
        "rotina_agendada_ativa":False,
        "publicacao_autorizada":False,
        "whatsapp_enviado":False,
        "aprovado_go_live":False,
        "motivo_bloqueio":"DIREITOS_POR_OPERACAO_PERSISTENCIA_E_HOMOLOGACAO_PENDENTES",
    }


def main() -> int:
    parser=argparse.ArgumentParser(description="Consulta interna PTAX USD, read-only e sem persistência")
    parser.add_argument("--consultar-bcb", action="store_true",
                        help="Único modo em que ocorre GET na API oficial")
    parser.add_argument("--mostrar-valores", action="store_true",
                        help="Apenas terminal interno; não usar em logs públicos")
    args=parser.parse_args()
    if not args.consultar_bcb:
        parser.error("--consultar-bcb explícito obrigatório: nunca executar rede por padrão")
    try:
        result=executar(agora=datetime.now(timezone.utc))
    except ErroPiloto as exc:
        parser.exit(2,"PILOTO_BLOQUEADO: "+str(exc)+"\n")
    if not args.mostrar_valores:
        for name in ("cotacao_compra","cotacao_venda",
                     "variacao_venda_pct_vs_dia_anterior_observado"):
            result.pop(name, None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"]=="PREVIA_INTERNA_VALIDA" else 2


if __name__=="__main__":
    raise SystemExit(main())
