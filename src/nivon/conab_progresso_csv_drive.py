"""Importador OFFLINE do histórico de progresso CONAB encontrado no Google Drive.

Grão: referência semanal × estado × operação × produto. Dado é fração 0..1,
NÃO produção em toneladas, rendimento, área nem média Brasil. Falta prova
independente de edição/publicação: nunca elegível a backtest as-of ou treino.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import sys


class ErroConabProgressoDrive(ValueError):
    pass


HEADER = ["", "Data", "Semana", "Mês", "Ano", "Estado",
          "Semeadura / Colheita", "Produto", "Dado", "INFO"]
UF = {
    "Bahia":"BA","Goiás":"GO","Maranhão":"MA",
    "Mato Grosso":"MT","Mato Grosso do Sul":"MS","Minas Gerais":"MG",
    "Paraná":"PR","Piauí":"PI","Rio Grande do Sul":"RS",
    "Santa Catarina":"SC","São Paulo":"SP","Tocantins":"TO",
}
MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
PRODUTOS = {"Soja":"SOJA", "Milho 1ª":"MILHO_1", "Milho 2ª":"MILHO_2",
            "Algodão":"ALGODAO"}
OPERACOES = {"Semeadura":"SEMEADURA", "Colheita":"COLHEITA"}
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def normalizar_csv_progresso_conab(
    *, raw_csv: bytes, sha256_esperado: str, adquirido_em: str,
) -> dict:
    """Lê CSV exportado de XLSX do Drive. Retém 1 observação por linha.

    Proibir usar como dado 2026-10 atual: a data máxima da fonte é a
    referência na planilha, não uma data de publicação/captura histórica.
    """
    if not isinstance(raw_csv, bytes) or not 30 <= len(raw_csv) <= 8_000_000:
        raise ErroConabProgressoDrive("CSV do Drive ausente ou excessivo")
    if not isinstance(sha256_esperado, str) or not _SHA.fullmatch(sha256_esperado):
        raise ErroConabProgressoDrive("hash de aquisição obrigatório")
    digest=sha256(raw_csv).hexdigest()
    if digest != sha256_esperado:
        raise ErroConabProgressoDrive("SHA CSV difere da captura")
    if not isinstance(adquirido_em, str) or "T" not in adquirido_em:
        raise ErroConabProgressoDrive("coleta do Drive com fuso é obrigatória")
    try:
        date=datetime.fromisoformat(adquirido_em.replace("Z","+00:00"))
    except ValueError as exc:
        raise ErroConabProgressoDrive("data da coleta inválida") from exc
    if date.tzinfo is None or date.utcoffset() is None:
        raise ErroConabProgressoDrive("data da coleta sem fuso")
    try:
        reader=csv.reader(StringIO(raw_csv.decode("utf-8-sig")))
        header=next(reader)
    except (UnicodeError, StopIteration, csv.Error) as exc:
        raise ErroConabProgressoDrive("CSV inválido") from exc
    if header != HEADER:
        raise ErroConabProgressoDrive("schema CSV não corresponde ao histórico do Drive")
    linhas=[]
    vistos=set()
    for idx,row in enumerate(reader):
        if not row:
            continue
        if idx >= 30000 or len(row) != len(HEADER):
            raise ErroConabProgressoDrive("linha excessiva ou com colunas incorretas")
        seq,dt,semana,mes,ano,estado,oper,produto,valor,info=row
        if not seq.isascii() or not seq.isdecimal() or int(seq)!=idx:
            raise ErroConabProgressoDrive("índice de linhas não sequencial")
        try:
            d=datetime.strptime(dt,"%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ErroConabProgressoDrive("data de referência semanal inválida") from exc
        if (not ano.isascii() or not ano.isdecimal()
                or int(ano)!=d.year or
                not semana.isascii() or not semana.isdecimal()
                or int(semana)!=d.isocalendar().week or
                mes!=MESES[d.month]):
            raise ErroConabProgressoDrive("calendário de referência inconsistente")
        if (estado not in UF or oper not in OPERACOES or produto not in PRODUTOS
                or info not in ("Brasil","MT") or
                (info=="MT") != (estado=="Mato Grosso")):
            raise ErroConabProgressoDrive("estado, operação, produto ou INFO inválidos")
        try:
            fraction=Decimal(valor)
        except InvalidOperation as exc:
            raise ErroConabProgressoDrive("percentual inválido") from exc
        if not fraction.is_finite() or not 0<=fraction<=1:
            raise ErroConabProgressoDrive("progresso exige fração 0..1")
        key=(d.date().isoformat(),UF[estado],OPERACOES[oper],PRODUTOS[produto])
        if key in vistos:
            raise ErroConabProgressoDrive("mesma observação semanal duplicada")
        vistos.add(key)
        linhas.append({
            "referencia":key[0],"uf":key[1],"operacao":key[2],
            "cultura_segmento":key[3],"progresso_fracao":str(fraction),
            "unidade":"FRACAO_0_1","origem_info":info,
            "fonte_importacao":"GOOGLE_DRIVE_CONAB_HISTORICO_USUARIO",
            "fonte_raw_sha256":digest,
            "publicado_em":None,"disponivel_em":None,
            "vintage_asof_comprovada":False,"observado_operacao_real":False,
        })
    if not linhas:
        raise ErroConabProgressoDrive("CSV sem registros")
    return {
        "status":"HISTORICO_DRIVE_NORMALIZADO_SEM_ASOF",
        "source_id":"CONAB_DERIVADO_ARQUIVO_DRIVE",
        "raw_sha256":digest,
        "adquirido_em":date.isoformat(),
        "total":len(linhas),
        "data_min":min(r["referencia"] for r in linhas),
        "data_max":max(r["referencia"] for r in linhas),
        "registros":linhas,
        "classificacao":"INFORMADO_ARQUIVO_DRIVE_NAO_HOMOLOGADO",
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Normaliza arquivo histórico CONAB do Drive, sem prover vintages")
    p.add_argument("--input",required=True)
    p.add_argument("--sha256",required=True)
    p.add_argument("--adquirido-em",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args(argv)
    try:
        inp,out=Path(args.input),Path(args.out)
        if inp.is_symlink() or not inp.is_file() or out.is_symlink() or out.exists():
            raise ErroConabProgressoDrive("arquivo inseguro ou saída existente")
        raw=inp.read_bytes()
        result=normalizar_csv_progresso_conab(
            raw_csv=raw,sha256_esperado=args.sha256,adquirido_em=args.adquirido_em)
        with out.open("x",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
        print(f"NORMALIZADOS={result['total']} ASOF=NAO")
        return 0
    except (ErroConabProgressoDrive,OSError,ValueError) as exc:
        print(f"Importação CONAB bloqueada: {exc}",file=sys.stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
