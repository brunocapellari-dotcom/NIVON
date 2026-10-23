#!/usr/bin/env python3
"""Comando único somente leitura para INTENÇÕES shadow D+7/30/90.

Não assina, não retrodata, não arquiva previsão, não faz rede nem divulga
valores para clientes. Requer cabeça do store recebida de fonte externa.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.parse import quote

from nivon.fretes_baseline_shadow import preparar_intencoes_baseline_frete
from nivon.fretes_ofertas_store import verificar_store_ofertas_frete
from nivon.fretes_previsoes_arquivadas import ErroAvaliacaoFrete
from nivon.fretes_registros import ErroRegistroFrete

CAMPOS=frozenset({
    "arquivo_ofertas_sqlite","cabeca_ofertas_sha256","condicoes",
    "fonte_id","emissor_id","horizontes_dias",
})
ECON=frozenset({
    "origem_ibge","destino_ibge","descarga_entity_id",
    "produto","equipamento","regime","pedagio",
})


def _privado(caminho: str, extensao: str, limite: int) -> Path:
    if not isinstance(caminho,str):
        raise ValueError("caminho local inválido")
    p=Path(caminho)
    if (p.suffix!=extensao or p.is_symlink() or not p.is_file()
            or not stat.S_ISREG(p.stat().st_mode)
            or p.stat().st_mode&0o077 or p.stat().st_size>limite):
        raise ValueError("arquivo privado ausente/inseguro")
    return p


def executar(config: dict, *, instante: datetime) -> dict:
    if not isinstance(config,dict) or set(config)!=CAMPOS:
        raise ValueError("configuração de emissão incompatível")
    opts=config["condicoes"]
    hs=config["horizontes_dias"]
    if (not isinstance(opts,dict) or set(opts)!=ECON
            or any(not isinstance(v,str) or not v for v in opts.values())
            or not isinstance(hs,list)):
        raise ValueError("condições econômicas/horizontes ausentes")
    path=_privado(config["arquivo_ofertas_sqlite"],".sqlite",100_000_000)
    uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True) as con:
        con.execute("PRAGMA query_only=ON")
        estado=verificar_store_ofertas_frete(
            con,cabeca_esperada_sha256=config["cabeca_ofertas_sha256"],
        )
    # Filtro de rota explícito: nunca agregar preços entre estabelecimentos,
    # transportadoras, regimes, veículos e locais de descarga distintos.
    matches=[]
    for r in estado["ofertas"]:
        matched=(
            r.municipio_ibge==opts["origem_ibge"]
            and r.destino_ibge==opts["destino_ibge"]
            and r.descarga_entity_id==opts["descarga_entity_id"]
            and r.produto==opts["produto"]
            and r.equipamento==opts["equipamento"]
            and r.regime==opts["regime"]
            and ("ADICIONAL" if r.pedagio_brl_t is not None
                 else "NAO_INFORMADO")==opts["pedagio"]
            and r.fonte_id==config["fonte_id"]
        )
        if matched:
            matches.append(r)
    resultado=preparar_intencoes_baseline_frete(
        matches,emitido_em=instante,
        fonte_id=config["fonte_id"],emissor_id=config["emissor_id"],
        horizontes_dias=tuple(hs),**opts,
    )
    return {
        **resultado,
        "cabeca_ofertas_sha256_conferida":estado["cabeca_sha256"],
        "total_de_ofertas_no_store":estado["registros"],
        "ofertas_elegiveis_nesta_rota":len(matches),
        "executor":"CLI_READONLY_SHADOW",
        "coleta_real_comprovada":False,
        "recebimento_ou_assinatura_externa_habilitados":False,
        "publicavel":False,
    }


def main() -> int:
    parser=argparse.ArgumentParser(description="Preparar previsões BASELINE shadow, sem gravar")
    parser.add_argument("--config",required=True)
    args=parser.parse_args()
    try:
        path=_privado(args.config,".json",8192)
        config=json.loads(path.read_text(encoding="utf-8"))
        out=executar(config,instante=datetime.now(timezone.utc))
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error,
            ErroRegistroFrete,ErroAvaliacaoFrete) as exc:
        print(json.dumps({
            "status":"EMISSAO_SHADOW_BLOQUEADA",
            "classe":type(exc).__name__,"publicavel":False,
        }),file=sys.stderr)
        return 2
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
