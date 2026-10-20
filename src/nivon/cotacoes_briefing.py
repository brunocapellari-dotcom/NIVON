"""Cotações licenciadas em pacote de briefing sem perder fuso, direitos ou prova.

Ponte offline. A autorização é injetada por um serviço operador confiável
separado do input de cotação; 'APROVADA' não comprova sozinha licença real.
Exige origem, hash de documento e timestamp de coleta. Nunca busca cotação.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from urllib.parse import urlsplit
import re

from .cotacoes_externas import cotacao_para_briefing, ErroMercado
from .indicadores_historicos import _instante


class ErroCotacoesIntegracao(ValueError):
    pass


_HOSTS={
    "CME":{"www.cmegroup.com","cmegroup.com"},
    "ICE":{"www.ice.com","ice.com"},
    "B3":{"www.b3.com.br","b3.com.br"},
    "CEPEA":{"www.cepea.esalq.usp.br","cepea.esalq.usp.br"},
    "IMEA":{"www.imea.com.br","imea.com.br"},
}
_SHA=re.compile(r"[0-9a-f]{64}\Z")


def preparar_cotacoes_licenciadas(*, cotacoes: list[dict],
                                 licencas_verificadas: dict,
                                 gerado_em: str, max_idade_horas: int = 168) -> dict:
    """Converte observações separadas em indicadores; erro bloqueia fonte.

    A entrega final DEVE recusar todo o pacote quando houver rejeições, em
    vez de enviar um briefing parcial sem os indicadores solicitados.
    """
    agora=_instante(gerado_em)
    if (not isinstance(cotacoes,list) or len(cotacoes)>80
        or not all(isinstance(x,dict) for x in cotacoes)
        or not isinstance(licencas_verificadas,dict)
        or type(max_idade_horas) is not int
        or not 1<=max_idade_horas<=336):
        raise ErroCotacoesIntegracao("contrato de mercado inválido")
    indicadores=[]
    evidencias=[]
    recusados=[]
    vistos=set()
    for i,item in enumerate(cotacoes):
        try:
            fid=item.get("fonte")
            if fid not in _HOSTS:
                raise ErroCotacoesIntegracao("fonte fora do contrato")
            direito=licencas_verificadas.get(fid)
            if not isinstance(direito,dict):
                raise ErroCotacoesIntegracao("licença não verificada")
            url=urlsplit(item.get("fonte_url",""))
            if (url.scheme!="https" or url.hostname not in _HOSTS[fid]
                or url.username or url.password or url.fragment
                or url.port not in (None,443)):
                raise ErroCotacoesIntegracao("domínio oficial de origem inválido")
            documento_sha=item.get("documento_sha256")
            if not isinstance(documento_sha,str) or not _SHA.fullmatch(documento_sha):
                raise ErroCotacoesIntegracao("hash do documento ausente")
            coleta=_instante(item.get("coletado_em"))
            referencia=_instante(item.get("referencia_em"))
            if referencia>agora or coleta>agora or coleta<referencia:
                raise ErroCotacoesIntegracao("relógio de cotação/coleta inconsistente")
            if agora-referencia>timedelta(hours=max_idade_horas):
                raise ErroCotacoesIntegracao("cotação vencida no corte")
            result=cotacao_para_briefing(item,direito,gerado_em=gerado_em)
            secao=("PRECOS" if item.get("tipo")=="INDICADOR_FISICO"
                   else "BOLSAS")
            # Fechamento deve ter data, fuso, fonte e contrato, não uma string
            # data-only que o briefing rejeitaria.
            if _instante(result["referencia"])!=referencia:
                raise ErroCotacoesIntegracao("normalizador perdeu precisão temporal")
            chave=(fid,secao,result["titulo"],result["referencia"])
            if chave in vistos:
                raise ErroCotacoesIntegracao("cotação duplicada: revisar vintages")
            vistos.add(chave)
            indicadores.append({
                "fonte_id":fid,"secao":secao,"titulo":result["titulo"],
                "valor":result["valor"],"referencia":result["referencia"],
                "fonte":f"{fid} {item['tipo']} - {item['fonte_url']}",
            })
            evidencias.append({
                "fonte_id":fid,"documento_sha256":documento_sha,
                "coletado_em":coleta.isoformat(),
                "referencia_em":referencia.isoformat(),
                "licenca_id":result["licenca_id"],
                "tipo":item["tipo"],"unidade":item["unidade"],
                "classificacao":"OBSERVACAO_DECLARADA_A_CONFIRMAR_COM_EVIDENCIA",
            })
        except (ValueError,TypeError,KeyError,AttributeError) as exc:
            # Não retornar preço nem dados de licença em diagnóstico de erro.
            recusados.append({"indice":i,"fonte":item.get("fonte"),
                              "status":"BLOQUEADO_VALIDACAO",
                              "classe_erro":type(exc).__name__})
    return {
        "status":"BLOQUEADO" if recusados else "NORMALIZADO_PARA_AUDITORIA",
        "indicadores":indicadores if not recusados else [],
        "evidencias":evidencias if not recusados else [],
        "recusados":recusados,
        "envio_automatico":False,
        "licenca_real_confirmada_pelo_codigo":False,
    }
