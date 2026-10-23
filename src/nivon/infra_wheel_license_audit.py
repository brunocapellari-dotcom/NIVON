"""Metadados de licenças de wheels já travadas por SHA-256, sem executar pacotes.

A licença do SOFTWARE não autoriza uso, revenda, redistribuição ou coleta
de dados de terceiros. Este relatório é diagnóstico, nunca decisão jurídica.
"""
from __future__ import annotations

import argparse
from collections import Counter
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile

from .infra_supplychain import ErroSupplyChain
from .infra_wheel_lock import coletar, verificar

MAX_METADATA = 512_000
DIST_INFO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,190}[.]dist-info/METADATA\Z")
SPDX = re.compile(r"[A-Za-z0-9.()+ _-]{1,250}\Z")


def _classificar(path: Path) -> str:
    try:
        with ZipFile(path) as zipfile:
            info = [i for i in zipfile.infolist() if DIST_INFO.fullmatch(i.filename)]
            if len(info) != 1 or not 0 < info[0].file_size <= MAX_METADATA:
                raise ErroSupplyChain("METADATA da wheel ausente/ambíguo/grande")
            if info[0].compress_size > MAX_METADATA:
                raise ErroSupplyChain("METADATA comprimido além do limite")
            raw = zipfile.open(info[0]).read(MAX_METADATA + 1)
            if not 0 < len(raw) <= MAX_METADATA:
                raise ErroSupplyChain("METADATA excede limite de leitura")
            msg = BytesParser(policy=policy.compat32).parsebytes(raw, headersonly=True)
    except (OSError, BadZipFile, EOFError, ValueError, RuntimeError) as exc:
        raise ErroSupplyChain("metadados de licença da wheel ilegíveis") from exc
    if msg.get("Name") is None or msg.get("Version") is None:
        raise ErroSupplyChain("METADATA sem identidade do pacote")
    lic = str(msg.get("License-Expression","")).strip()
    if lic and SPDX.fullmatch(lic):
        return "spdx_declarado"
    legacy = str(msg.get("License","")).strip()
    if legacy and legacy.upper() not in ("UNKNOWN", "NONE"):
        return "licenca_legada_declarada"
    classifiers = msg.get_all("Classifier") or []
    if any(str(c).startswith("License :: ") for c in classifiers):
        return "classificador_licenca"
    return "nao_identificada"


def auditar(folder: Path, arch: str, lock: Path) -> dict:
    observed = coletar(folder,arch)
    verificar(observed,lock)
    tally: Counter[str] = Counter()
    for item in observed["files"]:
        tally[_classificar(folder / item["filename"])] += 1
    if sum(tally.values()) != len(observed["files"]):
        raise ErroSupplyChain("cobertura de METADATA incompleta")
    return {
        "schema": "nivon.infrastructure.wheel_license_metadata.v1",
        "arch": arch,
        "verified_locked_wheels": len(observed["files"]),
        "declaracoes_por_formato": {
            name: tally[name] for name in (
                "spdx_declarado","licenca_legada_declarada",
                "classificador_licenca","nao_identificada")
        },
        "code_licenses_legally_reviewed": False,
        "notice_distribution_reviewed": False,
        "source_data_rights_authorized": False,
        "cepea_imea_conab_republication_authorized": False,
        "production_authorized": False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description="Inspeção offline de metadados de licenças")
    p.add_argument("--folder",required=True)
    p.add_argument("--arch",required=True,choices=("amd64","arm64"))
    p.add_argument("--lock",required=True)
    a=p.parse_args(argv)
    try:
        result=auditar(Path(a.folder),a.arch,Path(a.lock))
    except (OSError,ValueError):
        print(json.dumps({"status":"WHEEL_LICENSE_AUDIT_INCOMPLETE","production_authorized":False}))
        return 2
    print(json.dumps(result,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
