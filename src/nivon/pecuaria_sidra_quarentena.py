"""Captura direta de valores SIDRA em QUARENTENA, sem metadados API v3.

Nenhuma coleta/agendamento automatico. Nao alimenta produtos, relatorios de
mercado, modelos ou publicacao. Nao finge que o horario de coleta e o de
publicacao historica. Apenas a primeira observacao de uma revisao e conhecida.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from .cadeias_adicionais import TABELAS_SIDRA
from .motores import DadoInvalido
from .pecuaria_sidra_abate import normalizar_snapshot_sidra_abate
from .pecuaria_sidra_mapa_observado import contrato_sidra_observado
from .pecuaria_sidra_reconciliacao import diagnosticar_cobertura_abate
from .pecuaria_sidra_sondagem import _requisicao_https, _URL_VALORES

_SCHEMA = """
CREATE TABLE IF NOT EXISTS valores_pecuaria_quarentena (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  especie TEXT NOT NULL, tabela_sidra TEXT NOT NULL,
  periodo TEXT NOT NULL, territorio TEXT NOT NULL,
  url_declarada TEXT NOT NULL,
  primeira_coleta_em TEXT NOT NULL,
  sha256_bruto TEXT NOT NULL, bruto BLOB NOT NULL,
  estado TEXT NOT NULL CHECK(estado='QUARENTENA_VALUES_SEM_METADATA_V3'),
  UNIQUE(especie,tabela_sidra,periodo,territorio,sha256_bruto)
);
CREATE TRIGGER IF NOT EXISTS pecuaria_quarentena_sem_update
 BEFORE UPDATE ON valores_pecuaria_quarentena
 BEGIN SELECT RAISE(ABORT,'append_only'); END;
CREATE TRIGGER IF NOT EXISTS pecuaria_quarentena_sem_delete
 BEFORE DELETE ON valores_pecuaria_quarentena
 BEGIN SELECT RAISE(ABORT,'append_only'); END;
"""


def _conectar(banco, *, criar=False):
    if not isinstance(banco, (str, Path)) or type(criar) is not bool:
        raise DadoInvalido("caminho e modo obrigatorios")
    path = Path(banco).expanduser()
    if (any(p.is_symlink() for p in (path, *path.parents))
        or not path.parent.is_dir() or (path.exists() and not path.is_file())):
        raise DadoInvalido("caminho SQLite inseguro")
    if not criar and not path.is_file():
        raise DadoInvalido("quarentena SQLite nao existe")
    conn = (sqlite3.connect(str(path), timeout=5) if criar else
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                            uri=True, timeout=5))
    try:
        tem = conn.execute("""SELECT 1 FROM sqlite_master
                           WHERE name='valores_pecuaria_quarentena'
                             AND type='table'""").fetchone()
        if tem:
            # Nao modificar schema de arquivo antigo ou adulterado.
            columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(valores_pecuaria_quarentena)")}
            expected = {"id","especie","tabela_sidra","periodo","territorio",
                        "url_declarada","primeira_coleta_em","sha256_bruto",
                        "bruto","estado"}
            if columns != expected:
                raise DadoInvalido("quarentena com schema incompatível")
            # Nunca reconstruir indices/triggers faltantes silenciosamente.
            idx_esperado = ("especie","tabela_sidra","periodo",
                            "territorio","sha256_bruto")
            tem_unico = False
            for idx in conn.execute("PRAGMA index_list(valores_pecuaria_quarentena)"):
                if not idx[2]:
                    continue
                nome = idx[1].replace('"','""')
                cols = tuple(row[2] for row in conn.execute(
                    'PRAGMA index_info("' + nome + '")'))
                if cols == idx_esperado:
                    tem_unico = True
            triggers = {row[0] for row in conn.execute(
                """SELECT name FROM sqlite_master WHERE type='trigger'
                   AND tbl_name='valores_pecuaria_quarentena'""")}
            if (not tem_unico or not {
                "pecuaria_quarentena_sem_update",
                "pecuaria_quarentena_sem_delete"}.issubset(triggers)):
                raise DadoInvalido(
                    "quarentena legada sem unicidade/triggers; migracao auditada necessaria")
        elif not criar:
            raise DadoInvalido("tabela de quarentena inexistente")
        if criar:
            conn.executescript(_SCHEMA)
        return conn
    except Exception:
        conn.close()
        raise


def _url_values(tabela, periodo, territorio):
    if territorio not in ("BR","UFS"):
        raise DadoInvalido("territorio desconhecido")
    return (_URL_VALORES.format(tabela,periodo)
            .replace("/n1/1/", "/n1/1/" if territorio == "BR" else "/n3/all/")
            .replace("/v/allxp/", "/v/284,285/"))


def _preparar(*, periodo, transporte, timeout):
    if periodo != "202602":
        raise DadoInvalido("contrato de dimensoes observado apenas para 2026-T2")
    if not callable(transporte):
        raise DadoInvalido("transporte ausente")
    if type(timeout) not in (int,float) or isinstance(timeout,bool) or not 1 <= timeout <= 10:
        raise DadoInvalido("timeout fora do limite")
    capturas = []
    for especie in ("BOVINO","SUINO","FRANGO"):
        tabela = TABELAS_SIDRA[especie]
        mapa = contrato_sidra_observado(especie=especie,tabela_sidra=tabela)
        for territorio in ("BR","UFS"):
            url = _url_values(tabela,periodo,territorio)
            resposta = transporte(url=url,timeout=timeout,limite=2_000_000)
            if not isinstance(resposta,dict) or resposta.get("status_http") != 200:
                raise DadoInvalido("HTTP de captura SIDRA nao e 200")
            ct = resposta.get("content_type","")
            bruto = resposta.get("corpo")
            if (not isinstance(ct,str) or "json" not in ct.lower()
                or not isinstance(bruto,bytes) or not 2 <= len(bruto) <= 2_000_000):
                raise DadoInvalido("captura com tipo/bytes invalidos")
            # A hora da observacao e um limite CONSERVADOR, nao a hora da
            # publicacao do IBGE. Guardamos ambas as noções separadamente.
            agora = datetime.now(timezone.utc).isoformat()
            snap = normalizar_snapshot_sidra_abate(
                bruto, especie=especie, tabela_sidra=tabela,
                dimensoes=mapa["dimensoes"],totais=mapa["totais"],
                variaveis=mapa["variaveis"],
                publicacao=agora,coleta=agora,
                status_fonte="APROVADA",
                operacoes_autorizadas={"LEITURA","ARMAZENAMENTO"})
            if (territorio == "BR" and
                any(o.uf != "BR" for o in snap["observacoes"])):
                raise DadoInvalido("resposta BR contem UF")
            if (territorio == "UFS" and
                any(o.uf == "BR" for o in snap["observacoes"])):
                raise DadoInvalido("resposta UFS contem BR")
            capturas.append({"especie":especie,"tabela_sidra":tabela,
                             "periodo":periodo,"territorio":territorio,
                             "url_declarada":url,"primeira_coleta_em":agora,
                             "sha256_bruto":sha256(bruto).hexdigest(),
                             "bruto":bruto,"snapshot":snap})
    return capturas


def executar_captura_values_quarentena(
    *, periodo="202602", rede=False, direitos_confirmados=False,
    banco=None, gravar=False, timeout=8, transporte=None,
):
    """6 requests HTTPS somente com rede=True, preview se gravar=False.

    transporte e injetavel em testes; nunca autentica a origem. Direitos sao
    afirmacao do operador, nao comprovacao externa de termos da fonte.
    """
    if type(rede) is not bool or type(gravar) is not bool or type(direitos_confirmados) is not bool:
        raise DadoInvalido("flags devem ser booleanos")
    if periodo != "202602":
        raise DadoInvalido("mapeamento vigente somente no trimestre 202602")
    if gravar and (not direitos_confirmados or banco is None):
        raise PermissionError("gravar requer direitos confirmados e banco")
    if not rede and transporte is None:
        return {"status":"PLANEJADO_SEM_REDE","periodo":periodo,"gravado":False,
                "url_previstas":[_url_values(TABELAS_SIDRA[s],periodo,g)
                                for s in ("BOVINO","SUINO","FRANGO")
                                for g in ("BR","UFS")],
                "homologado":False}
    if not direitos_confirmados:
        raise PermissionError("captura requer confirmacao declarativa de direitos")
    fonte = transporte if transporte is not None else _requisicao_https
    capturas = _preparar(periodo=periodo,transporte=fonte,timeout=timeout)
    diagnosticos = []
    for especie in ("BOVINO","SUINO","FRANGO"):
        snaps = [c["snapshot"] for c in capturas if c["especie"] == especie]
        rel = diagnosticar_cobertura_abate(
            snapshots=snaps,especie=especie,tabela_sidra=TABELAS_SIDRA[especie],
            corte_asof=datetime.now(timezone.utc).isoformat())
        diagnosticos.append(rel)
    ids = []
    if gravar:
        with closing(_conectar(banco,criar=True)) as cx:
            with cx:
                cx.execute("BEGIN IMMEDIATE")
                for c in capturas:
                    key = (c["especie"],c["tabela_sidra"],c["periodo"],
                           c["territorio"],c["sha256_bruto"])
                    anterior = cx.execute(
                        """SELECT id,bruto FROM valores_pecuaria_quarentena
                           WHERE especie=? AND tabela_sidra=? AND periodo=?
                           AND territorio=? AND sha256_bruto=?""",key).fetchone()
                    if anterior:
                        if anterior[1] != c["bruto"]:
                            raise DadoInvalido("conflito com mesmo hash de captura")
                        ids.append(anterior[0])
                        continue
                    cx.execute("""INSERT INTO valores_pecuaria_quarentena(
                        especie,tabela_sidra,periodo,territorio,url_declarada,
                        primeira_coleta_em,sha256_bruto,bruto,estado)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (*key[:4],c["url_declarada"],c["primeira_coleta_em"],
                         key[4],c["bruto"],"QUARENTENA_VALUES_SEM_METADATA_V3"))
                    ids.append(cx.execute("SELECT last_insert_rowid()").fetchone()[0])
    return {"status":"QUARENTENA_VALUES_SEM_METADATA_V3",
            "periodo":periodo,"gravado":gravar,"ids":ids,
            "consulta_externa_executada":bool(rede and transporte is None),
            "capturas":[{"especie":c["especie"],"territorio":c["territorio"],
                         "sha256":c["sha256_bruto"],
                         "registros":len(c["snapshot"]["observacoes"]),
                         "censuras":len(c["snapshot"]["linhas_indisponiveis"])}
                        for c in capturas],
            "diagnosticos":diagnosticos,
            "primeiro_conhecimento_por_coleta":True,
            "publicacao_historica_confirmada":False,
            "metadata_v3_confirmado":False,"homologado":False,
            "publicacao_permitida":False}


def recuperar_values_quarentena(*, banco, id_captura):
    """Leitura sem DDL e integridade antes de expor bytes ao normalizador."""
    if type(id_captura) is not int or id_captura < 1:
        raise DadoInvalido("id invalido")
    with closing(_conectar(banco,criar=False)) as cx:
        linha = cx.execute(
            """SELECT especie,tabela_sidra,periodo,territorio,url_declarada,
                      primeira_coleta_em,sha256_bruto,bruto,estado
               FROM valores_pecuaria_quarentena WHERE id=?""",
            (id_captura,)).fetchone()
    if linha is None:
        raise DadoInvalido("captura nao encontrada")
    esp,tab,per,geo,url,coleta,hash_,bruto,status = linha
    if (TABELAS_SIDRA.get(esp) != tab or per != "202602"
        or url != _url_values(tab,per,geo)
        or status != "QUARENTENA_VALUES_SEM_METADATA_V3"
        or not isinstance(bruto,bytes) or sha256(bruto).hexdigest() != hash_):
        raise DadoInvalido("integridade/identidade de quarentena corrompidas")
    return {"especie":esp,"tabela_sidra":tab,"periodo":per,"territorio":geo,
            "url_declarada":url,"primeira_coleta_em":coleta,
            "sha256_bruto":hash_,"bruto":bruto,"status":status,
            "metadata_v3_confirmado":False,"homologado":False}


def main(argv=None):
    """Operacao manual e explicita. Nunca agenda nem envia dados para terceiros."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        description="NIVON: consulta IBGE values em quarentena (sem metadata v3)")
    parser.add_argument("--periodo", default="202602")
    parser.add_argument("--rede", action="store_true",
                        help="opt-in para seis requisicoes HTTPS oficiais")
    parser.add_argument("--confirmar-direitos", action="store_true",
                        help="declara direitos de consulta/armazenamento")
    parser.add_argument("--gravar", action="store_true",
                        help="armazena JSONs de values no banco SQLite local")
    parser.add_argument("--banco", help="caminho de SQLite fora do repositorio")
    args = parser.parse_args(argv)
    try:
        resposta = executar_captura_values_quarentena(
            periodo=args.periodo, rede=args.rede,
            direitos_confirmados=args.confirmar_direitos,
            gravar=args.gravar, banco=args.banco)
        print(json.dumps(resposta, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (DadoInvalido, PermissionError, OSError, ValueError) as exc:
        print(json.dumps({"status":"BLOQUEADO","erro":type(exc).__name__,
                          "detalhe":str(exc)[:150]},ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
