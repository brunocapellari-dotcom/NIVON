"""Exportação offline do snapshot anual ANTT em JSONL compatível com BigQuery.
Não realiza chamadas nem cria recursos Google Cloud: exige carga autorizada.
"""
import json
import os
import sqlite3
import tempfile
from pathlib import Path

CAMPOS=("sha256","ano","origem_uf","origem_rgi","destino_uf","destino_rgi",
 "toneladas","participacao_pct","data_referencia","competencia","data_publicacao",
 "data_coleta","fonte","classificacao","escopo","granularidade")

def preparar(banco):
    with sqlite3.connect(banco) as con:
        con.row_factory=sqlite3.Row
        lote=con.execute("""SELECT sha256,ano,data_referencia,competencia,data_publicacao,
                            data_coleta,url,classificacao
                            FROM antt_anuario_rgi_lotes
                            ORDER BY data_coleta DESC,sha256 DESC LIMIT 1""").fetchone()
        if lote is None:
            raise ValueError("SEM_DADOS_ANTT_RGI")
        linhas=con.execute("""SELECT ano,origem_uf,origem_rgi,destino_uf,destino_rgi,
                              toneladas,participacao_pct FROM antt_anuario_rgi_fluxos
                              WHERE sha256=? ORDER BY origem_uf,origem_rgi,destino_uf,destino_rgi""",
                              (lote["sha256"],)).fetchall()
        if len(linhas)!=16:
            raise ValueError("RUPTURA_DE_SNAPSHOT_ANUARIO")
        saida=[]
        for linha in linhas:
            registro={k:linha[k] for k in linha.keys()}
            registro.update({
                "sha256":lote["sha256"],"data_referencia":lote["data_referencia"],
                "competencia":lote["competencia"],"data_publicacao":lote["data_publicacao"],
                "data_coleta":lote["data_coleta"],"fonte":lote["url"],
                "classificacao":lote["classificacao"],
                "escopo":"TOP_16_FLUXOS_GERAIS_ANUAIS","granularidade":"RGI"})
            saida.append({k:registro[k] for k in CAMPOS})
        return saida

def exportar(banco, saida):
    dados=preparar(banco)
    destino=Path(saida)
    destino.parent.mkdir(parents=True,exist_ok=True)
    fd,nome=tempfile.mkstemp(prefix=".antt-",suffix=".jsonl",dir=destino.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            for row in dados:
                f.write(json.dumps(row,ensure_ascii=False,sort_keys=True)+"\n")
        os.replace(nome,destino)
    finally:
        if os.path.exists(nome):
            os.unlink(nome)
    return {"estado":"JSONL_CRIADO_NAO_ENVIADO","registros":len(dados),
            "sha256_fonte":dados[0]["sha256"]}
