"""Ponte IVO somente leitura para edições CONAB já armazenadas no NIVON.

A CONAB oferece safras informadas/projetadas: NÃO converter essas séries em
rótulos realizados, nem misturar safra com calendário mensal. Nenhuma consulta
externa, autorização de coleta, atualização de DB ou treinamento aqui.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from math import isfinite

from .conab_series import ARQUIVOS, UF

class ErroPonteConab(ValueError):
    pass

SHA=re.compile(r"[0-9a-f]{64}\Z")
SAFRA=re.compile(r"((?:19|20)\d{2})/((?:19|20)\d{2})\Z")
CLASSIFICACOES=frozenset({"INFORMADO_CONAB_NAO_CERTIFICA_REALIZADO","PROJETADO_CONAB"})
UNIDADES={"PRODUCAO":"T","AREA":"HA","PRODUTIVIDADE":"KG_HA"}


def _utc(valor):
    if not isinstance(valor,datetime):
        try: valor=datetime.fromisoformat(valor.replace("Z","+00:00"))
        except (ValueError,TypeError,AttributeError) as exc:
            raise ErroPonteConab("corte exige data/hora válida") from exc
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ErroPonteConab("corte exige fuso horário")
    return valor.astimezone(timezone.utc)


def _safra(valor):
    if not isinstance(valor,str) or not SAFRA.fullmatch(valor):
        raise ErroPonteConab("safra fora do formato AAAA/AAAA")
    primeiro,segundo=map(int,valor.split("/"))
    if segundo!=primeiro+1:
        raise ErroPonteConab("anos da safra não são consecutivos")
    return primeiro


def consultar_safras_conab(
    db:sqlite3.Connection,*,arquivo:str,uf:str,indicador:str,
    corte:datetime,limite_safras:int=50,
)->dict:
    """Seleciona a última edição capturada/publicada por safra até o corte.

    O retorno preserva fonte, competência, natureza e desconhecimento de
    direito de uso; não cria Observacao(OBSERVADO) nem ativa aprendizado.
    """
    if not isinstance(db,sqlite3.Connection):
        raise ErroPonteConab("conexão SQLite canônica requerida")
    if arquivo not in ARQUIVOS or uf not in UF or indicador not in UNIDADES:
        raise ErroPonteConab("arquivo, UF ou indicador não homologado")
    if type(limite_safras) is not int or not 1<=limite_safras<=100:
        raise ErroPonteConab("limite_safras fora de faixa")
    instante=_utc(corte)
    # Evita misturar uma revisão adquirida depois do corte, mesmo que refira
    # safra anterior. Exige publicação conhecida; sem publicação, não
    # há base para afirmar que a edição estava disponível ao público.
    rows=db.execute("""
      SELECT o.produto,o.subdivisao,o.uf,o.safra,o.indicador,o.unidade,
             o.valor,o.classe,o.fonte_sha,e.publicado_em,c.coletado_utc,
             o.cabecalho_inferido
      FROM conab_observacoes o
      JOIN conab_edicoes e ON e.fonte_sha=o.fonte_sha AND e.arquivo=o.arquivo
      JOIN conab_coletas c ON c.fonte_sha=o.fonte_sha AND c.arquivo=o.arquivo
      WHERE o.arquivo=? AND o.uf=? AND o.indicador=?
        AND e.publicado_em IS NOT NULL
        AND e.publicado_em <= ?
        AND c.coletado_utc <= ?
      ORDER BY o.safra, c.coletado_utc DESC, e.publicado_em DESC, o.fonte_sha DESC
      LIMIT 20000
    """,(arquivo,uf,indicador,instante.date().isoformat(),instante.isoformat())).fetchall()
    if len(rows)>=20000:
        raise ErroPonteConab("histórico acima do limite de inspeção")
    produto,subdiv=ARQUIVOS[arquivo]
    out={}
    for raw in rows:
        (prod,sub,region,safra,indicador_lido,unidade,valor,classe,sha,
         publicacao,coleta,inferido)=tuple(raw)
        if (prod,sub,region,indicador_lido)!=(produto,subdiv,uf,indicador):
            raise ErroPonteConab("escopo de série CONAB inconsistente com arquivo")
        _safra(safra)
        if unidade!=UNIDADES[indicador] or classe not in CLASSIFICACOES:
            raise ErroPonteConab("unidade ou classificação CONAB inválida")
        if type(valor) not in (float,int) or not isfinite(valor) or valor<0:
            raise ErroPonteConab("valor CONAB inválido")
        if not isinstance(sha,str) or not SHA.fullmatch(sha):
            raise ErroPonteConab("edição sem SHA-256")
        publicado=datetime.fromisoformat(publicacao+"T00:00:00+00:00")
        coletado=_utc(coleta)
        if publicado>coletado or coletado>instante or publicado.date()>instante.date():
            raise ErroPonteConab("datas de publicação/coleta inconsistentes")
        if inferido not in (0,1):
            raise ErroPonteConab("indicação de cabeçalho inferido desconhecida")
        if safra not in out:
            out[safra]={
                "safra":safra,"produto":produto,"subdivisao_safra":subdiv,
                "uf":uf,"indicador":indicador,"unidade":unidade,
                "valor":float(valor),"classificacao":classe,
                "publicado_em":publicacao,"coletado_em":coletado.isoformat(),
                "fonte_sha256":sha,"cabecalho_inferido":bool(inferido),
                "observado_final_certificado":False,
                "autorizado_para_treino_supervisionado":False,
            }
    if len(out)>limite_safras:
        raise ErroPonteConab("mais safras do que o limite solicitado")
    return {
        "estado":"SERIES_CONAB_ASOF_NAO_HOMOLOGADAS_TREINO",
        "fonte":"CONAB","arquivo":arquivo,"uf":uf,"indicador":indicador,
        "calendario":"SAFRA","corte":instante.isoformat(),
        "safras":len(out),
        "observacoes":[out[k] for k in sorted(out,key=_safra)],
        "rótulos_realizados_disponiveis":0,
        "treinamento_supervisionado_habilitado":False,
        "direitos_de_uso_confirmados":False,
        "observacao":"A planilha informa safras mas não certifica resultado final realizado; "
                     "não converter INFORMADO/PROJETADO em OBSERVADO.",
    }
