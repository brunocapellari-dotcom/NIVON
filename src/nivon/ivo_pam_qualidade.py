"""Auditoria integrada: cada vintage PAM armazenada corresponde aos bytes em disco.

Executa em SQLite + quarentena existentes, sem coletar, alterar
registros ou presumir licenças. Detecta inconsistência de valor/célula,
recibo perdido, alteração de bytes e violações de integridade SQL.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .ivo_pam_quarentena import conferir_recibo_pam, ErroQuarentenaPAM
from .sidra_pam import planejar_pam_1612, normalizar_pam_1612


class ErroQualidadePAM(ValueError):
    pass


def auditar_operacao_pam(*,db:sqlite3.Connection,raiz,max_vintages:int=3000)->dict:
    if not isinstance(db,sqlite3.Connection) or type(max_vintages) is not int or not 1<=max_vintages<=10000:
        raise ErroQualidadePAM("parâmetros de auditoria inválidos")
    integridade=db.execute("PRAGMA integrity_check").fetchone()[0]
    violacoes=db.execute("PRAGMA foreign_key_check").fetchall()
    rows=db.execute("""SELECT municipio,ano,variavel,produto,sha256,
       estado_valor,valor,unidade,recibo_sha256,origem_url
       FROM pam_vintages ORDER BY municipio,ano,variavel,produto,sha256
       LIMIT ?""",(max_vintages+1,)).fetchall()
    if len(rows)>max_vintages:
        raise ErroQualidadePAM("vintages demais; auditar em lotes de origem")
    erros=[]
    root=Path(raiz)
    for v in rows:
        chave=f"{v['municipio']}:{v['ano']}:{v['variavel']}:{v['produto']}:{v['sha256'][:12]}"
        try:
            verificado=conferir_recibo_pam(raiz=root,recibo_sha256=v["recibo_sha256"])
            if verificado["sha256"]!=v["sha256"]:
                raise ErroQualidadePAM("hash de recibo aponta para outra edição")
            recibo=root/"recibos"/(v["recibo_sha256"]+".json")
            meta=json.loads(recibo.read_text(encoding="utf-8"))
            if (meta.get("url_declarada")!=v["origem_url"] or
                meta.get("tipo")!="SIDRA_JSON"):
                raise ErroQualidadePAM("URL/identidade do recibo divergentes do SQL")
            obj=root/"objetos_sha256"/(v["sha256"]+".bin")
            plano=planejar_pam_1612(
                municipio_ibge=v["municipio"],ano=v["ano"],
                codigo_produto_c81=v["produto"],codigo_variavel=v["variavel"])
            if v["origem_url"]!=plano["url"]:
                raise ErroQualidadePAM("URL diferente do plano SIDRA original")
            normalizado=normalizar_pam_1612(
                obj.read_bytes(),plano=plano,coletado_em=meta["captura_declarada_em"])
            if len(normalizado["observacoes"])!=1:
                raise ErroQualidadePAM("número de observações divergente")
            o=normalizado["observacoes"][0]
            if (o["estado_valor"]!=v["estado_valor"] or
                o["valor"]!=v["valor"] or
                o["unidade_original"]!=v["unidade"]):
                raise ErroQualidadePAM("registro SQL não reproduz valor, estado ou unidade")
            capt=db.execute("""SELECT COUNT(*) FROM pam_capturas
                WHERE municipio=? AND ano=? AND variavel=? AND produto=? AND sha256=?""",
                (v["municipio"],v["ano"],v["variavel"],v["produto"],v["sha256"])).fetchone()[0]
            if capt<1:
                raise ErroQualidadePAM("edição não possui captura registrada")
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
            erros.append({"vintage":chave,"problema":str(exc)[:180]})
    total_capturas=db.execute("SELECT COUNT(*) FROM pam_capturas").fetchone()[0]
    return {
        "estado":"INTEGRIDADE_LOCAL_VERIFICADA" if integridade=="ok" and not violacoes and not erros
                 else "INTEGRIDADE_LOCAL_FALHOU",
        "sqlite_integridade":integridade,
        "erros_chaves_estrangeiras":len(violacoes),
        "vintages_verificadas":len(rows),
        "capturas_registradas":total_capturas,
        "erros":erros[:100],
        "integridade_local_aprovada":integridade=="ok" and not violacoes and not erros,
        "dados_reais_homologados":False,
        "releases_oficiais_verificados":False,
        "treinamento_real_liberado":False,
    }
