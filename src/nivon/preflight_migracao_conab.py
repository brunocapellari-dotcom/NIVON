"""Pré-voo read-only de migração dos dois históricos semanais CONAB.

NUNCA grava, migra, registra direitos ou afirma que o replay JSON foi gerado
a partir do RAW: arquivo-fonte, parser e licença ainda exigem auditoria externa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

from .conciliacao_progresso_stores import (
    ErroConciliacaoConab, _abrir_readonly, _auditar_integridade_bancos,
    _json_pares_unicos, _normalizar_registro, _timestamp, _url,
    _verificar_esquemas,
)
from .verificador_bytes_origem import conferir_bytes_origem, ErroBytesOrigem
from .conab_replay_raw import PARSER_ID, ErroReplayConab, reexecutar_csv_conab
from .conab_replay_xlsx import PARSER_ID as XLSX_PARSER_ID, ErroXlsxProgresso, reexecutar_xlsx_conab

_SCHEMA = "NIVON_CONAB_PREFLIGHT_V1"
_DATASET = "CONAB_PROGRESSO_SEMANAL"
_SHA = frozenset("0123456789abcdef")
_MIMES = frozenset({
    "text/csv", "text/plain", "application/pdf", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
})
_MAX_EDICOES = 500
_MAX_ROWS = 20000
_MAX_RAW = 20_000_000


class ErroPreflightConab(ValueError):
    pass


def _sha256(valor: str) -> str:
    if (not isinstance(valor, str) or len(valor) != 64
            or any(x not in _SHA for x in valor)):
        raise ErroPreflightConab("SHA-256 inválido")
    return valor


def _json_limpo(path: Path, limite: int):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limite:
        raise ErroPreflightConab("arquivo de evidência inválido, symlink ou fora do limite")
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          object_pairs_hook=_json_pares_unicos)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ErroPreflightConab("JSON de evidência inválido") from exc


def _raw_local(path: Path, sha: str, mime: str, tamanho: int) -> dict:
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or type(tamanho) is not int or not 0 < tamanho <= _MAX_RAW
            or path.stat().st_size != tamanho):
        raise ErroPreflightConab("RAW ausente, symlink, tamanho ou caminho inválido")
    if mime not in _MIMES:
        raise ErroPreflightConab("MIME RAW não esperado para boletim CONAB")
    try:
        payload = path.read_bytes()
        return conferir_bytes_origem(
            payload=payload, sha256_informado=sha,
            tamanho_informado=tamanho, mime=mime)
    except (OSError, ErroBytesOrigem) as exc:
        raise ErroPreflightConab("RAW não passou validação local de bytes") from exc


def _registros_replay(path: Path):
    out = _json_limpo(path, 2_000_000)
    if not isinstance(out, list) or not 1 <= len(out) <= 5000:
        raise ErroPreflightConab("replay JSON deve conter de 1 a 5000 linhas")
    rows = {}
    for rec in out:
        if not isinstance(rec, dict):
            raise ErroPreflightConab("linha replay não é objeto")
        # O parser offline gera coleta; ela pertence ao ledger, não ao hash.
        if "coleta" in rec:
            _timestamp(rec["coleta"])
        raw = dict(rec)
        raw.pop("coleta", None)
        try:
            key, semantic, obj = _normalizar_registro(
                json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False))
        except (ErroConciliacaoConab, TypeError, ValueError) as exc:
            raise ErroPreflightConab("linha de replay fora do contrato canônico") from exc
        if key in rows:
            raise ErroPreflightConab("chave duplicada no replay")
        rows[key] = semantic
    return rows


def _legado_edicoes(legado: sqlite3.Connection, limite: int) -> dict[int, dict]:
    rows = legado.execute("""SELECT e.id,e.fonte_url,e.sha256_json,e.publicado_utc,
            e.observado_semana,e.evidence_id,e.numero_linhas,
            o.registro_json
            FROM progresso_edicoes e
            JOIN progresso_observacoes o ON o.edicao_id=e.id
            ORDER BY e.id,o.cultura,o.safra,o.operacao,o.uf,o.semana
            LIMIT ?""",(limite+1,)).fetchall()
    if len(rows) > limite:
        raise ErroPreflightConab("observações legadas acima do limite de pré-voo")
    edicoes = {}
    for sid,url,sha,pub,semana,evidence_id,num,obs in rows:
        _sha256(sha)
        _url(url)
        key, semantic, item = _normalizar_registro(obs)
        if (item["source_url"] != url or item["competencia"] != semana
                or (pub is None) != (item["publicacao"] is None)):
            raise ErroPreflightConab("metadados de edição legada divergem do registro")
        if pub is not None and _timestamp(pub).isoformat() != item["publicacao"]:
            raise ErroPreflightConab("publicação ISO divergente entre linhas e edição")
        if type(num) is not int or num < 1 or not isinstance(evidence_id,str):
            raise ErroPreflightConab("contagem/evidência legada inválida")
        ed = edicoes.setdefault(sid, {
            "id":sid,"url":url,"sha_json":sha,"publicacao":pub,
            "semana":semana,"contagem":num,"evidence_id":evidence_id,
            "rows":{},
        })
        if (ed["url"],ed["sha_json"],ed["publicacao"],ed["semana"],ed["contagem"]) != (url,sha,pub,semana,num):
            raise ErroPreflightConab("metadados mutáveis dentro da edição legada")
        if key in ed["rows"]:
            raise ErroPreflightConab("observação duplicada dentro da edição legada")
        ed["rows"][key] = semantic
    for ed in edicoes.values():
        if len(ed["rows"]) != ed["contagem"]:
            raise ErroPreflightConab("quantidade de observações de edição divergente")
    return edicoes


def _canonico_por_sha(db: sqlite3.Connection, sha: str):
    snaps = db.execute("""SELECT id,dataset_id,fonte_id,sha256,tipo,publicacao
         FROM nivon_snapshots WHERE dataset_id=? AND sha256=?""",
         (_DATASET,sha)).fetchall()
    if len(snaps) > 1:
        raise ErroPreflightConab("SHA RAW duplicado no ledger canônico")
    if not snaps:
        return None
    sid,dataset,source,hash_,tipo,pub=snaps[0]
    if (dataset != _DATASET or source != "CONAB" or hash_ != sha
            or tipo not in ("SINTETICO","REAL_AUTORIZADO")):
        raise ErroPreflightConab("snapshot canônico inconsistente")
    lines = db.execute("SELECT chave,observacao_json FROM nivon_conab_progresso WHERE snapshot_id=?",
                       (sid,)).fetchall()
    if not lines:
        raise ErroPreflightConab("snapshot com SHA presente mas sem observações")
    rows = {}
    for chave,obs in lines:
        key,semantic,r=_normalizar_registro(obs)
        try:
            stored_key=json.loads(chave,object_pairs_hook=_json_pares_unicos)
        except (TypeError,ValueError) as exc:
            raise ErroPreflightConab("chave JSON inválida no ledger") from exc
        if list(key)!=stored_key or key in rows:
            raise ErroPreflightConab("chaves canônicas conflitantes ou duplicadas")
        if (pub is None) != (r["publicacao"] is None):
            raise ErroPreflightConab("publicação canônica distinta das observações")
        if pub is not None and pub != r["publicacao"][:10]:
            raise ErroPreflightConab("data de publicação no snapshot divergente")
        rows[key]=semantic
    captures = db.execute("SELECT coletado_utc FROM nivon_coletas WHERE snapshot_id=?",
                          (sid,)).fetchall()
    if not captures:
        raise ErroPreflightConab("snapshot sem coleta no ledger")
    return {"rows":rows,"capturas":set(_timestamp(x[0]).isoformat() for x in captures),
            "tipo":tipo}


def planejar_preflight_conab(legado: sqlite3.Connection,
                            canonico: sqlite3.Connection,
                            manifesto: dict, *,
                            limite: int = _MAX_ROWS) -> dict:
    """Plano de migração sem escrituras; toda edição deve ter evidência independente.

    Um JSON 'reprocessado' não estabelece vínculo físico com o RAW: a verificação
    do parser e a licença permanecem gates externos mesmo se tudo conferir.
    """
    if type(limite) is not int or not 1 <= limite <= _MAX_ROWS:
        raise ErroPreflightConab("limite fora do contrato")
    if (not isinstance(manifesto, dict) or set(manifesto) != {"schema","edicoes"}
            or manifesto["schema"] != _SCHEMA
            or not isinstance(manifesto["edicoes"], list)
            or len(manifesto["edicoes"]) > _MAX_EDICOES):
        raise ErroPreflightConab("manifesto precisa seguir schema V1")
    _verificar_esquemas(legado, canonico)
    _auditar_integridade_bancos(legado, canonico, limite)
    originals = _legado_edicoes(legado, limite)
    refs = {}
    for row in manifesto["edicoes"]:
        if not isinstance(row,dict) or set(row) != {
            "legacy_id","sha256_json","url_origem","raw_path","raw_sha256",
            "raw_bytes","raw_mime","replay_json_path","parser_versao",
            "direitos_evidencia_id",
        }:
            raise ErroPreflightConab("entrada do manifesto incompleta")
        sid = row["legacy_id"]
        if type(sid) is not int or sid <= 0 or sid in refs:
            raise ErroPreflightConab("ID legado repetido ou inválido")
        if sid not in originals:
            raise ErroPreflightConab("manifesto referencia edição que não existe")
        refs[sid]=row
    info=[]
    estados=Counter()
    raw_to_edition={}
    for sid in sorted(originals):
        ed=originals[sid]
        prova=refs.get(sid)
        replay_executado=False
        xlsx_executado=False
        parser_code_sha=None
        if prova is None:
            estado="SEM_MANIFESTO_RAW"
            hashes=None
            replay_count=None
        else:
            if (prova["sha256_json"] != ed["sha_json"]
                    or _url(prova["url_origem"]) != ed["url"]):
                raise ErroPreflightConab("manifesto não corresponde à edição histórica")
            raw_hash=_sha256(prova["raw_sha256"])
            if raw_hash in raw_to_edition and raw_to_edition[raw_hash] != sid:
                raise ErroPreflightConab("mesmo RAW associado a edições legadas diferentes")
            raw_to_edition[raw_hash]=sid
            for field in ("parser_versao","direitos_evidencia_id"):
                if (not isinstance(prova[field],str) or not 1<=len(prova[field])<=100):
                    raise ErroPreflightConab("versão de parser/prova de direitos ausente")
            _raw_local(Path(prova["raw_path"]),raw_hash,prova["raw_mime"],prova["raw_bytes"])
            rows = _registros_replay(Path(prova["replay_json_path"]))
            if rows != ed["rows"]:
                raise ErroPreflightConab("replay declarado diverge do histórico legado")
            if prova["parser_versao"] == PARSER_ID:
                if prova["raw_mime"] != "text/csv":
                    raise ErroPreflightConab("parser de intercâmbio requer CSV")
                coleta_db=legado.execute("""SELECT MIN(coletado_utc)
                    FROM progresso_coletas WHERE edicao_id=?""",(sid,)).fetchone()[0]
                if coleta_db is None:
                    raise ErroPreflightConab("edição legada sem coleta")
                try:
                    executado = reexecutar_csv_conab(
                        Path(prova["raw_path"]).read_bytes(),
                        sha256_origem=raw_hash, url_origem=ed["url"],
                        coletado_em=coleta_db, publicado_em=ed["publicacao"])
                except (ErroReplayConab,OSError) as exc:
                    raise ErroPreflightConab("RAW não pôde ser reprocessado pelo parser de laboratório") from exc
                if executado["mapa_semantico"] != rows:
                    raise ErroPreflightConab("RAW reprocessado diverge do replay/legado")
                replay_executado=True
                parser_code_sha=executado["parser_codigo_sha256"]
            if prova["parser_versao"] == XLSX_PARSER_ID:
                if prova["raw_mime"] != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                    raise ErroPreflightConab("parser XLSX exige MIME XLSX")
                coleta_db=legado.execute("""SELECT MIN(coletado_utc)
                    FROM progresso_coletas WHERE edicao_id=?""",(sid,)).fetchone()[0]
                if coleta_db is None:
                    raise ErroPreflightConab("edição legada sem coleta")
                try:
                    executado_xlsx = reexecutar_xlsx_conab(
                        Path(prova["raw_path"]).read_bytes(),
                        sha256_origem=raw_hash, url_origem=ed["url"],
                        coletado_em=coleta_db, publicado_em=ed["publicacao"])
                except (ErroXlsxProgresso,OSError) as exc:
                    raise ErroPreflightConab("XLSX bruto não foi processado no contrato conhecido") from exc
                if executado_xlsx["mapa_semantico"] != rows:
                    raise ErroPreflightConab("XLSX RAW reprocessado diverge do replay/legado")
                xlsx_executado=True
                parser_code_sha=executado_xlsx["parser_codigo_sha256"]
            match = _canonico_por_sha(canonico,raw_hash)
            if match is not None:
                if match["rows"] != rows:
                    raise ErroPreflightConab("conflito: RAW SHA já no canônico com observações diferentes")
                # Capturas antigas podem divergir mesmo com conteúdo idêntico.
                estado="SHA_RAW_PRESENTE_NO_CANONICO_CONFERIR_CAPTURAS"
            else:
                estado=("RAW_XLSX_REFERENCIA_PUBLICA_REPROCESSADO_SEM_HOMOLOGACAO"
                        if xlsx_executado else
                        "RAW_CSV_INTERCAMBIO_REPROCESSADO_SEM_HOMOLOGACAO_CONAB"
                        if replay_executado else "RAW_E_REPLAY_LOCAIS_CONFERIDOS_SEM_PROVA_DO_PARSER")
            hashes={"raw_sha256":raw_hash,"normalizado_sha256":ed["sha_json"]}
            replay_count=len(rows)
        estados[estado]+=1
        info.append({
            "legacy_id":sid,
            "semana":ed["semana"],
            "estado":estado,
            "observacoes_legadas":ed["contagem"],
            "observacoes_replay":replay_count,
            "hashes":hashes,
            "parser_raw_reprodutivel_auditado":False,
            "csv_intercambio_reexecutado_localmente":replay_executado,
            "xlsx_reexecutado_localmente_sem_homologacao":xlsx_executado,
            "parser_codigo_sha256":parser_code_sha,
            "direitos_validados_externamente":False,
            "origem_oficial_comprovada_externamente":False,
            "pronto_para_migracao":False,
        })
    return {
        "schema":_SCHEMA,
        "dataset_id":_DATASET,
        "edicoes_legadas":len(originals),
        "edicoes_com_evidencia":len(refs),
        "replays_csv_intercambio_executados":sum(x["csv_intercambio_reexecutado_localmente"] for x in info),
        "replays_xlsx_publicos_executados":sum(x["xlsx_reexecutado_localmente_sem_homologacao"] for x in info),
        "parser_conab_oficial_homologado":False,
        "por_estado":dict(sorted(estados.items())),
        "itens":info,
        "plano_de_execucao":"SOMENTE_DRY_RUN_SEM_SQL_DE_MIGRACAO",
        "backup_verificado":False,
        "restauracao_testada":False,
        "snapshot_canonico_compatibilizado":False,
        "arquivo_bruto_para_parser_reexecutado_pelo_modulo":False,
        "direitos_coleta_armazenamento_derivacao_publicacao_verificados":False,
        "migracao_permitida":False,
        "integracao_para_producao":False,
        "pendencias":["VALIDAR_DIREITOS_EXTERNAMENTE","REEXECUTAR_PARSER_DOS_BYTES_RAW_COM_TRILHA_ASSINADA",
                     "BACKUP_RESTAURACAO_TESTADOS","RECONCILIAR_VINTAGES_E_CAPTURAS","REVISOR_INDEPENDENTE"],
    }


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="Pré-voo migratório CONAB (sem gravar dados)")
    p.add_argument("--legado",required=True)
    p.add_argument("--canonico",required=True)
    p.add_argument("--manifesto",required=True)
    p.add_argument("--resumo",action="store_true")
    args=p.parse_args(argv)
    opened=[]
    try:
        doc = _json_limpo(Path(args.manifesto),2_000_000)
        for filename in (args.legado,args.canonico):
            opened.append(_abrir_readonly(filename))
        output=planejar_preflight_conab(opened[0],opened[1],doc)
        if args.resumo:
            output.pop("itens")
        print(json.dumps(output,ensure_ascii=False,indent=2,sort_keys=True))
    except (sqlite3.Error,OSError,ErroPreflightConab,ErroConciliacaoConab) as exc:
        p.error(str(exc))
    finally:
        for conn in opened:
            conn.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
