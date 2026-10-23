"""CLI de processamento completo RONI offline: manifesto -> QA -> arquivo RAW + SQLite.

Uso:
 python -m nivon.roni_cli validar --manifesto lotes.json
 python -m nivon.roni_cli executar --manifesto lotes.json --banco roni.sqlite \
     --raw-dir arquivo_raw --confirmar-gravacao-local

Não lê rede, não agenda tarefas, não publica resultados.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .noaa_roni import ErroRONI, MAX_RAW_BYTES, importar_roni_ascii
from .roni_store import (abrir_arquivo_roni, executar_lote_roni,
                         panorama_local_roni)


def _load_manifest(path):
    src = Path(path)
    if (src.is_symlink() or not src.is_file()
            or src.suffix.lower() != ".json"
            or src.stat().st_size > 200_000):
        raise ErroRONI("manifesto RONI JSON inválido ou excessivo")
    try:
        obj = json.loads(src.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ErroRONI("manifesto JSON malformado") from exc
    if (not isinstance(obj, dict) or set(obj) !=
            {"schema_version", "project", "lotes"} or
            obj["project"] != "NIVON" or obj["schema_version"] != "1.0" or
            not isinstance(obj["lotes"], list) or
            not 1 <= len(obj["lotes"]) <= 50):
        raise ErroRONI("manifesto não corresponde ao contrato de lote NIVON")
    base = src.resolve().parent
    items, seen = [], set()
    for entry in obj["lotes"]:
        if (not isinstance(entry, dict) or set(entry) !=
                {"arquivo", "coletado_em", "classe"}):
            raise ErroRONI("lote sem campos obrigatórios")
        name = entry["arquivo"]
        if (not isinstance(name, str) or len(name) > 160
                or Path(name).is_absolute() or "/" in name or "\\" in name
                or name in (".", "..") or not name.endswith(".ascii")):
            raise ErroRONI("nome de arquivo RONI fora do diretório do manifesto")
        if name in seen:
            raise ErroRONI("arquivo de lote duplicado")
        seen.add(name)
        file = base / name
        if file.is_symlink() or not file.is_file() or not file.resolve().parent == base:
            raise ErroRONI("lote RAW ausente, inseguro ou symlink")
        if not 10 < file.stat().st_size <= MAX_RAW_BYTES:
            raise ErroRONI("tamanho de lote fora do limite")
        raw = file.read_bytes()
        parsed = importar_roni_ascii(
            raw=raw, coletado_em=entry["coletado_em"])
        if entry["classe"] not in ("SINTETICO", "EXTERNO_NAO_HOMOLOGADO"):
            raise ErroRONI("classe de lote inválida")
        items.append({
            "raw": raw, "coletado_em": entry["coletado_em"],
            "classe": entry["classe"], "sha256": sha256(raw).hexdigest(),
            "filename": name, "numero_temporadas": parsed["quantidade"],
        })
    return items


def executar_manifesto_roni(
    *, manifesto, modo="validar", banco=None,
    raw_dir=None, confirmar_gravacao_local=False,
):
    """Preflight de todos os arquivos antes de qualquer gravação local."""
    if modo not in ("validar", "executar"):
        raise ErroRONI("modo RONI inválido")
    items = _load_manifest(manifesto)
    if modo == "validar":
        return {
            "estado": "PREFLIGHT_OK_SEM_ESCRITA",
            "lotes": len(items),
            "arquivos": [{"nome": i["filename"], "sha256": i["sha256"],
                          "temporadas": i["numero_temporadas"]}
                         for i in items],
            "gravacoes": 0, "http": 0,
            "homologado": False,
        }
    if (confirmar_gravacao_local is not True or
            not isinstance(banco, (str, Path)) or not banco or
            not isinstance(raw_dir, (str, Path)) or not raw_dir):
        raise PermissionError("gravação local requer confirmação, DB e diretório RAW")
    path = Path(banco)
    if path == Path(":memory:") or path.is_symlink():
        raise ErroRONI("pipeline requer DB SQLite persistente, não memória/symlink")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise ErroRONI("diretório de DB inexistente ou symlink")
    db = abrir_arquivo_roni(path)
    try:
        results = []
        for item in items:
            result = executar_lote_roni(
                db, raw_dir=raw_dir, raw=item["raw"],
                coletado_em=item["coletado_em"], classe=item["classe"])
            results.append({"arquivo": item["filename"], **result})
        types = sorted(set(item["classe"] for item in items))
        return {
            "estado": "LOTES_PERSISTIDOS_OFFLINE_NAO_HOMOLOGADOS",
            "lotes_processados": len(results),
            "resultados": results,
            "panoramas": {t: panorama_local_roni(
                db, raw_dir=raw_dir, classe=t) for t in types},
            "http": 0, "agendamento": False, "publicacao": False,
            "homologado": False,
        }
    finally:
        db.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="NIVON RONI: pipeline offline")
    ap.add_argument("modo", choices=["validar", "executar"])
    ap.add_argument("--manifesto", required=True)
    ap.add_argument("--banco")
    ap.add_argument("--raw-dir")
    ap.add_argument("--confirmar-gravacao-local", action="store_true")
    a = ap.parse_args(argv)
    try:
        result = executar_manifesto_roni(
            manifesto=a.manifesto, modo=a.modo, banco=a.banco,
            raw_dir=a.raw_dir,
            confirmar_gravacao_local=a.confirmar_gravacao_local)
    except (ErroRONI, PermissionError, OSError, ValueError) as exc:
        print(json.dumps({"estado": "BLOQUEADO",
                          "tipo": type(exc).__name__, "motivo": str(exc)},
                         ensure_ascii=False))
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
