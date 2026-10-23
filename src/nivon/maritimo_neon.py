"""Replicação transacional de capturas/revisões marítimas locais para Neon.

Não cria credenciais, não imprime DSN e nunca converte informações
programadas, CDP não validada ou AIS inferida em operações realizadas.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def conexao_neon():
    dsn = os.environ.get("NIVON_MARITIMO_DSN", "").strip()
    if not dsn:
        raise RuntimeError("NIVON_MARITIMO_DSN nao configurado no secret vault")
    import psycopg  # import opcional, somente em rotina habilitada
    return psycopg.connect(dsn, connect_timeout=12, sslmode="require")


def _ler_sqlite(caminho, tabela, *, opcional=False):
    if tabela not in {"capturas", "revisoes", "portwatch_diario", "lote_execucoes"}:
        raise ValueError("tabela nao autorizada")
    if not Path(caminho).is_file():
        raise FileNotFoundError("arquivo SQLite de ingestao nao existe")
    with sqlite3.connect(str(caminho)) as con:
        con.row_factory = sqlite3.Row
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone()
        if not exists:
            if opcional:
                return []
            raise ValueError("tabela de historico obrigatoria ausente")
        return [dict(row) for row in con.execute("SELECT * FROM " + tabela)]


def sincronizar(destino, banco_lineup, *, banco_portwatch=None):
    """Somente inserts idempotentes e ultima observacao; SQL parametrizado."""
    fontes = _ler_sqlite(banco_lineup, "capturas")
    escalas = _ler_sqlite(banco_lineup, "revisoes")
    fluxos = _ler_sqlite(banco_portwatch, "portwatch_diario") if banco_portwatch else []
    execucoes = _ler_sqlite(banco_lineup, "lote_execucoes", opcional=True)
    with destino.transaction():
        for r in fontes:
            destino.execute("""
                INSERT INTO nivon_maritimo.capturas
                  (fonte, hash_conteudo, primeiro_visto, ultimo_visto, registros, qualidade)
                VALUES (%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(fonte,hash_conteudo) DO UPDATE SET
                   ultimo_visto=GREATEST(nivon_maritimo.capturas.ultimo_visto,EXCLUDED.ultimo_visto)
            """, (r["fonte"],r["hash_conteudo"],r["primeiro_visto"],r["ultimo_visto"],
                  r["quantidade"],r["qualidade"]))
        for r in escalas:
            data = json.loads(r["conteudo_json"])
            flags = data.get("flags_qualidade", [])
            is_public = bool(r["publicavel"]) and "QUARENTENA_NAO_PUBLICAR" not in flags
            destino.execute("""
                INSERT INTO nivon_maritimo.escalas_revisoes
                 (fonte,escala_id,revisao_sha256,coletado_em,natureza,situacao,publicavel,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(fonte,escala_id,revisao_sha256) DO NOTHING
            """, (r["fonte"],r["escala"],r["revisao"],r["primeiro_visto"],
                  data.get("natureza","DESCONHECIDO"),data.get("status"),is_public,
                  r["conteudo_json"]))
        for r in execucoes:
            destino.execute("""
                INSERT INTO nivon_maritimo.coleta_execucoes
                (run_id,fonte,coletado_em,estado,quantidade,revisoes,
                 captura_sha256,motivo,duracao_ms)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(run_id,fonte) DO NOTHING
            """, (r["run_id"],r["fonte"],r["coletado_em"],r["estado"],
                  r["quantidade"],r["revisoes"],r["captura_sha256"],r["motivo"],r["duracao_ms"]))
        for r in fluxos:
            data = json.loads(r["dados_json"])
            if data.get("volume_realizado_t") is not None:
                raise ValueError("PortWatch nao comprova tonelagem efetivamente realizada")
            destino.execute("""
                INSERT INTO nivon_maritimo.fluxos_passagens
                 (fonte,passagem,data_referencia,revisao_sha256,coletado_em,
                  transitos_ais,capacidade_proxy,payload)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT(fonte,passagem,data_referencia,revisao_sha256) DO NOTHING
            """, ("FMI_PORTWATCH",r["passagem"],r["data_referencia"],r["revisao_sha256"],
                  r["coletado_em"],data["transitos_ais"],data.get("volume_transito_estimado_t"),
                  r["dados_json"]))
    report = {"capturas_processadas":len(fontes),"revisoes_processadas":len(escalas),
              "passagens_processadas":len(fluxos)}
    if execucoes:
        report["execucoes_processadas"] = len(execucoes)
    return report


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--banco",type=Path,required=True)
    p.add_argument("--portwatch-banco",type=Path)
    opt=p.parse_args(argv)
    if not opt.banco.exists():
        raise SystemExit("Banco SQLite de coleta nao encontrado")
    with conexao_neon() as target:
        report=sincronizar(target,opt.banco,banco_portwatch=opt.portwatch_banco)
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
