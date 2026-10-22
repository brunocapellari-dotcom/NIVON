"""Exportação controlada do stage FAOSTAT QCL para JSONL BigQuery.

Sem cliente GCP nem ação de escrita na nuvem. Invocação explícita permite
produzir um lote portátil a partir do SQLite versionado e verificável.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

COLUNAS = ("dataset_id","pais","cultura","area_code","item_code",
           "element_code","ano","unidade","valor","flag_fonte",
           "data_referencia","competencia","data_publicacao","data_coleta",
           "data_atualizacao_fonte","source_sha256")


class ErroExportacaoQCL(ValueError):
    pass


def _validar(row):
    if (row["dataset_id"] != "FAO_FAOSTAT_LONG_RUN" or
            row["pais"] not in {"BRA","ARG","USA"} or
            row["cultura"] not in {"SOJA","MILHO","TRIGO"} or
            row["element_code"] != "5510" or row["unidade"] != "t"):
        raise ErroExportacaoQCL("identidade de estatística inesperada")
    a = row["ano"]
    if type(a) is not int or not 1961 <= a <= 2100:
        raise ErroExportacaoQCL("ano inválido")
    if row["competencia"] != str(a) or row["data_referencia"] != str(a):
        raise ErroExportacaoQCL("referência e competência divergentes")
    if row["data_publicacao"] is not None:
        raise ErroExportacaoQCL("publicação preenchida sem origem auditada")
    if not isinstance(row["source_sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",row["source_sha256"]):
        raise ErroExportacaoQCL("SHA de origem inválido")
    if not isinstance(row["data_coleta"],str):
        raise ErroExportacaoQCL("coleta ausente")
    try:
        dt = datetime.fromisoformat(row["data_coleta"].replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroExportacaoQCL("data_coleta inválida") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ErroExportacaoQCL("coleta sem timezone")
    try:
        value = Decimal(row["valor"])
    except (InvalidOperation,TypeError) as exc:
        raise ErroExportacaoQCL("valor QCL inválido") from exc
    if not value.is_finite() or value < 0 or value > Decimal("100000000000000"):
        raise ErroExportacaoQCL("valor QCL fora de faixa")
    return {
        **row,
        "data_referencia": date(a,12,31).isoformat(),
        "valor": format(value,"f"),
        "flag_fonte":row["flag_fonte"] or None,
        "data_publicacao":None,
        "source_id":"FAO",
        "dominio":"QCL",
    }


def exportar_stage_jsonl(*, banco_sqlite: str, saida_jsonl: str,
                         max_linhas: int = 20_000) -> dict:
    """Escreve lote JSONL atômico com JSON seguro; NÃO acessa BigQuery."""
    if (not isinstance(banco_sqlite,str) or not banco_sqlite or
            banco_sqlite == ":memory:" or not os.path.isfile(banco_sqlite)):
        raise ErroExportacaoQCL("SQLite stage deve existir em arquivo local")
    if (not isinstance(saida_jsonl,str) or not saida_jsonl or
            not saida_jsonl.endswith(".jsonl") or
            os.path.abspath(saida_jsonl) == os.path.abspath(banco_sqlite)):
        raise ErroExportacaoQCL("caminho de saída inválido")
    if type(max_linhas) is not int or not 1<=max_linhas<=100_000:
        raise ErroExportacaoQCL("limite inválido")
    outpath=os.path.abspath(saida_jsonl)
    destdir=os.path.dirname(outpath)
    if not os.path.isdir(destdir):
        raise ErroExportacaoQCL("diretório de destino inexistente")
    checksum=hashlib.sha256()
    count=0
    tmpname=None
    con=sqlite3.connect(f"file:{os.path.abspath(banco_sqlite)}?mode=ro",uri=True)
    con.row_factory=sqlite3.Row
    try:
        with tempfile.NamedTemporaryFile(mode="wb",prefix=".nivon_qcl_",suffix=".part",
                                         dir=destdir,delete=False) as out:
            tmpname=out.name
            query=("SELECT "+",".join(COLUNAS)+
                   " FROM faostat_qcl_snapshot ORDER BY pais,cultura,ano,source_sha256")
            for row in con.execute(query):
                count+=1
                if count>max_linhas:
                    raise ErroExportacaoQCL("número de linhas ultrapassa limite do lote")
                validated=_validar(dict(row))
                line=(json.dumps(validated,ensure_ascii=False,
                                 sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
                out.write(line)
                checksum.update(line)
            if count==0:
                raise ErroExportacaoQCL("stage sem observações")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmpname,outpath)
        tmpname=None
    except Exception:
        if tmpname is not None:
            os.unlink(tmpname)
        raise
    finally:
        con.close()
    return {"dataset_id":"FAO_FAOSTAT_LONG_RUN",
            "linhas":count,"sha256_jsonl":checksum.hexdigest(),
            "formato":"BIGQUERY_JSONL_CANDIDATO",
            "bigquery_upload_executado":False,
            "cloud_resources_criados":False,
            "apto_publicacao_automatica":False}
