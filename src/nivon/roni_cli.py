"""CLI de processamento completo RONI offline: manifesto -> QA -> arquivo RAW + SQLite.

Uso:
 python -m nivon.roni_cli validar --manifesto lotes.json
 python -m nivon.roni_cli executar --manifesto lotes.json --banco roni.sqlite \
     --raw-dir arquivo_raw --confirmar-gravacao-local
 Opcional pontual HTTPS (somente após direitos por operação verificados):
 python -m nivon.roni_cli capturar --banco roni.sqlite --raw-dir arquivo_raw \
     --confirmar-gravacao-local --autorizar-http --direitos-fonte REF_LICENCA

Não lê rede, não agenda tarefas, não publica resultados.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from .noaa_roni import ErroRONI, MAX_RAW_BYTES, importar_roni_ascii
from .roni_store import (abrir_arquivo_roni, executar_lote_roni,
                         panorama_local_roni, auditar_acervo_roni)


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
        from .roni_ciclo import processar_ciclo_roni
        result = processar_ciclo_roni(db, raw_dir=raw_dir, itens=items)
        types = sorted(set(item["classe"] for item in items))
        return {
            **result,
            "panoramas": {t: panorama_local_roni(
                db, raw_dir=raw_dir, classe=t) for t in types},
        }
    finally:
        db.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="NIVON RONI: pipeline offline")
    ap.add_argument("modo", choices=["validar", "executar", "capturar", "auditar", "relatorio", "backup", "validar-backup"])
    ap.add_argument("--manifesto")
    ap.add_argument("--banco")
    ap.add_argument("--raw-dir")
    ap.add_argument("--confirmar-gravacao-local", action="store_true")
    ap.add_argument("--autorizar-http", action="store_true")
    ap.add_argument("--direitos-fonte")
    ap.add_argument("--confirmar-revisao", action="store_true")
    ap.add_argument("--classe", default="SINTETICO")
    ap.add_argument("--corte-em")
    ap.add_argument("--destino-backup")
    a = ap.parse_args(argv)
    try:
        if a.modo == "validar-backup":
            if not a.destino_backup:
                raise ErroRONI("pasta do backup obrigatória")
            from .roni_ciclo import validar_backup_roni
            result = validar_backup_roni(caminho=a.destino_backup)
        elif a.modo in ("relatorio", "backup"):
            if not a.banco or not a.raw_dir or not Path(a.banco).is_file():
                raise ErroRONI("acervo SQLite pré-existente obrigatório")
            from .roni_ciclo import relatorio_revisoes_roni, gerar_backup_roni
            db = abrir_arquivo_roni(a.banco)
            try:
                if a.modo == "relatorio":
                    result = relatorio_revisoes_roni(
                        db, raw_dir=a.raw_dir, classe=a.classe,
                        corte_em=a.corte_em)
                else:
                    if not a.destino_backup:
                        raise ErroRONI("pasta de destino backup obrigatória")
                    result = gerar_backup_roni(
                        db, raw_dir=a.raw_dir, destino=a.destino_backup)
            finally:
                db.close()
        elif a.modo == "auditar":
            if not a.banco or not a.raw_dir or not Path(a.banco).is_file():
                raise ErroRONI("acervo SQLite pré-existente obrigatório na auditoria")
            db = abrir_arquivo_roni(a.banco)
            try:
                result = auditar_acervo_roni(db, raw_dir=a.raw_dir)
            finally:
                db.close()
        elif a.modo == "capturar":
            if not a.confirmar_gravacao_local or not a.banco or not a.raw_dir:
                raise PermissionError("captura requer persistência local explicitamente autorizada")
            from .roni_captura_manual import (
                capturar_roni_manual, exigir_direitos_catalogo_roni,
            )
            if a.autorizar_http is not True:
                raise PermissionError("HTTP da NOAA desabilitado até opt-in")
            # Não criar SQLite vazio nem inicializar RAW antes de conferir
            # direitos e estado operacional pelo catálogo mestre.
            exigir_direitos_catalogo_roni()
            db = abrir_arquivo_roni(a.banco)
            try:
                result = capturar_roni_manual(
                    db, raw_dir=a.raw_dir, autorizar_http=a.autorizar_http,
                    autorizacoes=frozenset({"COLETA", "ARMAZENAMENTO"})
                        if a.direitos_fonte else frozenset(),
                    evidencia_direitos=a.direitos_fonte,
                    confirmar_revisao=a.confirmar_revisao)
            finally:
                db.close()
        else:
            if not a.manifesto:
                raise ErroRONI("manifesto exigido no modo offline")
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
