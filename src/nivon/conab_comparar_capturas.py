"""Comparação OFFLINE entre CAPTURAS de XLSX CONAB em staging SQLite.

Detecta hashes, diferenças de layout e mudanças em CELULAS AMOSTRADAS.
Não equiparar diferenças de capturas a revisão oficial ou vintage point-in-time.
Não lê rede, não altera SQLite e não informa produção agrícola realizada.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import sys


class ErroComparacaoCapturas(ValueError):
    pass


_SHA = re.compile(r"[a-f0-9]{64}\Z")


def _abrir_amostra(raw: str) -> tuple:
    if not isinstance(raw, str) or len(raw) > 180_000:
        raise ErroComparacaoCapturas("layout_json excessivo")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ErroComparacaoCapturas("layout_json não legível") from exc
    if (not isinstance(doc, dict) or
            doc.get("estado") != "AMOSTRA_OOXML_SEM_TABELA_AGRICOLA_HOMOLOGADA" or
            doc.get("habilita_backtest") is not False or
            doc.get("habilita_publicacao") is not False or
            doc.get("tabela_agricola_normalizada") is not False):
        raise ErroComparacaoCapturas("layout não é staging não homologado")
    abas = doc.get("abas")
    if not isinstance(abas, list) or not 1 <= len(abas) <= 8:
        raise ErroComparacaoCapturas("abas da amostra inválidas")
    indexes = {}
    abas_ids = set()
    for aba in abas:
        if not isinstance(aba, dict):
            raise ErroComparacaoCapturas("aba de layout inválida")
        nome = aba.get("nome_aba")
        cells = aba.get("amostra_celulas")
        if (not isinstance(nome, str) or not 1 <= len(nome) <= 31 or
                nome.casefold() in abas_ids or not isinstance(cells, list)
                or len(cells) > 500):
            raise ErroComparacaoCapturas("amostra de aba inválida")
        abas_ids.add(nome.casefold())
        for cell in cells:
            if not isinstance(cell, dict):
                raise ErroComparacaoCapturas("célula de layout inválida")
            pos, typ, value = cell.get("referencia"), cell.get("tipo"), cell.get("valor")
            if (not isinstance(pos, str) or not re.fullmatch(r"[A-Z]{1,3}[1-9]\d{0,6}",pos)
                    or not isinstance(typ,str) or not 1 <= len(typ) <= 40
                    or value is not None and (not isinstance(value, str) or len(value) > 2500)):
                raise ErroComparacaoCapturas("célula com formato inválido")
            key = (nome.casefold(), pos)
            if key in indexes:
                raise ErroComparacaoCapturas("célula duplicada na amostra")
            indexes[key] = (typ,value)
    return frozenset(abas_ids), indexes


def _diferencas_antigas_novas(layout_a, layout_b, limite: int) -> dict:
    tabs_a, a = _abrir_amostra(layout_a)
    tabs_b, b = _abrir_amostra(layout_b)
    if tabs_a != tabs_b:
        return {
            "estado": "ABAS_DIFERENTES_COMPARACAO_NAO_HOMOLOGADA",
            "total_celulas_alteradas_na_amostra": None,
            "mudancas_na_amostra": [],
            "limitado": False,
        }
    chaves=sorted(set(a)|set(b))
    diffs=[]
    total=0
    for k in chaves:
        if a.get(k) != b.get(k):
            total += 1
            if len(diffs) < limite:
                old = a.get(k)
                new = b.get(k)
                diffs.append({
                    "aba":k[0],"celula":k[1],
                    "antes":None if old is None else {"tipo":old[0],"valor":old[1]},
                    "depois":None if new is None else {"tipo":new[0],"valor":new[1]},
                })
    return {
        "estado":"AMOSTRAS_COMPARADAS_SEM_PROVA_DE_REVISAO_OFICIAL",
        "total_celulas_alteradas_na_amostra":total,
        "mudancas_na_amostra":diffs,
        "limitado":total>len(diffs),
    }


def comparar_capturas_sqlite(*, arquivo_sqlite: str | Path,
                             limite_mudancas: int=40) -> dict:
    if type(limite_mudancas) is not int or not 1 <= limite_mudancas <= 100:
        raise ErroComparacaoCapturas("limite_mudancas fora do contrato")
    path=Path(arquivo_sqlite)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 50_000_000:
        raise ErroComparacaoCapturas("SQLite ausente, symlink ou excessivo")
    try:
        uri="file:"+path.resolve().as_posix()+"?mode=ro"
        with sqlite3.connect(uri,uri=True,timeout=3) as db:
            db.execute("PRAGMA query_only=ON")
            rows=db.execute(
                """SELECT id,safra,numero_levantamento,arquivo_sha256,
                          captura_primeira_utc,layout_json
                   FROM nivon_conab_staging_documentos
                   WHERE classe_status='OFFLINE_SEM_VINTAGE'
                   ORDER BY safra,numero_levantamento,id LIMIT 1001"""
            ).fetchall()
    except sqlite3.Error as exc:
        raise ErroComparacaoCapturas("SQLite de staging não consultável") from exc
    if len(rows)>1000:
        raise ErroComparacaoCapturas("muitas capturas em staging")
    grupos={}
    for row_id, safra, numero, digest, data_captura, layout in rows:
        if not isinstance(digest,str) or not _SHA.fullmatch(digest):
            raise ErroComparacaoCapturas("hash de captura inválido")
        grupos.setdefault((safra,numero),[]).append(
            {"id":row_id,"hash":digest,"captura":data_captura,"layout":layout}
        )
    changes=[]
    for (safra,numero),capturas in sorted(grupos.items()):
        for before, after in zip(capturas,capturas[1:]):
            diff=_diferencas_antigas_novas(before["layout"],after["layout"],limite_mudancas)
            changes.append({
                "safra":safra,"numero_levantamento":numero,
                "id_captura_anterior":before["id"],
                "id_captura_posterior":after["id"],
                "sha256_anterior":before["hash"],"sha256_posterior":after["hash"],
                "data_declarada_anterior":before["captura"],
                "data_declarada_posterior":after["captura"],
                **diff,
                "revisao_oficial_conab_comprovada":False,
                "vintage_asof_comprovada":False,
            })
    return {
        "estado":"DIFERENCAS_ENTRE_CAPTURAS_STAGING_NAO_HOMOLOGADAS",
        "capturas":len(rows),"grupos_edicoes":len(grupos),
        "pares_comparados":len(changes),"comparacoes":changes,
        "comparacao_exaustiva_de_celulas":False,
        "revisao_oficial_conab_comprovada":False,
        "disponibilidade_historica_comprovada":False,
        "habilita_backtest":False,"habilita_treino":False,
        "habilita_publicacao":False,
        "nota":"Amostras de células, não séries completas; IDs seguem ordem de gravação, não cronologia oficial.",
    }


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="Compara capturas XLSX CONAB em SQLite local")
    p.add_argument("--sqlite",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args(argv)
    try:
        result=comparar_capturas_sqlite(arquivo_sqlite=args.sqlite)
        out=Path(args.out)
        if out.exists() or out.is_symlink() or not out.parent.is_dir():
            raise ErroComparacaoCapturas("destino já existe ou é inseguro")
        if out.resolve() == Path(args.sqlite).resolve():
            raise ErroComparacaoCapturas("não substituir banco de staging")
        with out.open("x",encoding="utf-8") as handle:
            json.dump(result,handle,ensure_ascii=False,indent=2,allow_nan=False)
            handle.write("\n")
        print(f"CAPTURAS={result['capturas']} PARES={result['pares_comparados']}")
        return 0
    except (ErroComparacaoCapturas,OSError,ValueError) as exc:
        print(f"REJEITADO: {exc}",file=sys.stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
