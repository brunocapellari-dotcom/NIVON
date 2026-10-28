"""Cloud Run Job `nivon-coletor`: executa as fontes e grava a saúde no BigQuery.

Uma fonte que falha não impede as demais; o job termina com código 1 se
qualquer fonte falhou, para o Cloud Run registrar a execução como falha.
Fail-closed: sem NIVON_COLETOR_HABILITADO=true nada é executado.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.carga.registro_fontes import FONTES, Contexto

TABELA_SAUDE = "nivon_core.saude_fontes"
TIMEOUT_ETAPA_S = 900
PROJETO_ESPERADO = "nivon-data"
EXECUCAO = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
# Início das execuções varia alguns minutos; sem folga, 11:15 -> 17:15 pularia a fonte de 6 h.
FOLGA = timedelta(minutes=30)


def ultimas_execucoes_ok(projeto, *, cliente=None, sdk=None):
    """Início da última execução OK por fonte (8 dias de partição, no máximo 100 MB)."""
    if sdk is None:
        from google.cloud import bigquery as sdk
    cliente = cliente or sdk.Client(project=projeto, location="southamerica-east1")
    sql = (f"SELECT fonte, MAX(inicio) AS ultima FROM `{projeto}.{TABELA_SAUDE}` "
           "WHERE status = 'OK' AND DATE(inicio) >= DATE_SUB(CURRENT_DATE(), INTERVAL 8 DAY) "
           "GROUP BY fonte")
    cfg = sdk.QueryJobConfig(maximum_bytes_billed=100_000_000)
    return {linha["fonte"]: linha["ultima"] for linha in cliente.query(sql, job_config=cfg).result()}


def fontes_vencidas(nomes, ultimas, agora):
    """Fonte sem execução OK conhecida é sempre vencida."""
    vencidas = []
    for nome in nomes:
        ultima = ultimas.get(nome)
        if ultima is None or agora - ultima >= FONTES[nome].intervalo - FOLGA:
            vencidas.append(nome)
    return vencidas


def executar_fonte(fonte, ctx, *, runner=subprocess.run, relogio=time.monotonic,
                   agora=lambda: datetime.now(timezone.utc)):
    """Roda as etapas em ordem e para na primeira falha. Não guarda stdout."""
    inicio, t0 = agora(), relogio()
    env = {**os.environ, **fonte.env, "PYTHONPATH": os.pathsep.join(
        filter(None, [str(Path.cwd()), str(Path.cwd() / "src"), os.environ.get("PYTHONPATH")]))}
    status, etapa_falha, codigo = "OK", None, 0
    for n, cmd in enumerate(fonte.etapas(ctx), 1):
        modulo = cmd[2] if len(cmd) > 2 else cmd[0]
        print(json.dumps({"fonte": fonte.nome, "etapa": n, "modulo": modulo}), flush=True)
        try:
            r = runner(cmd, env=env, timeout=TIMEOUT_ETAPA_S, check=False)
            codigo = r.returncode
        except subprocess.TimeoutExpired:
            codigo = 124
        if codigo != 0:
            status, etapa_falha = "FALHA", f"{n}:{modulo}"
            break
    return {"fonte": fonte.nome, "status": status, "etapa_falha": etapa_falha,
            "codigo_saida": codigo, "inicio": inicio.isoformat(), "fim": agora().isoformat(),
            "duracao_s": round(relogio() - t0, 3)}


def registrar_saude(resultados, *, execucao_id, revisao, projeto, cliente=None, sdk=None):
    """MERGE por (execucao_id, fonte): reexecutar a mesma execução não duplica."""
    if sdk is None:
        from google.cloud import bigquery as sdk
    cliente = cliente or sdk.Client(project=projeto, location="southamerica-east1")
    tabela = f"`{projeto}.{TABELA_SAUDE}`"
    sql = (f"MERGE {tabela} T USING (SELECT @execucao_id execucao_id, @fonte fonte) S "
           "ON T.execucao_id = S.execucao_id AND T.fonte = S.fonte "
           "AND DATE(T.inicio) = DATE(TIMESTAMP(@inicio)) "
           "WHEN MATCHED THEN UPDATE SET status=@status, etapa_falha=@etapa_falha, "
           "codigo_saida=@codigo_saida, fim=TIMESTAMP(@fim), duracao_s=@duracao_s, "
           "registrado_em=CURRENT_TIMESTAMP() "
           "WHEN NOT MATCHED THEN INSERT (execucao_id, fonte, status, etapa_falha, codigo_saida, "
           "inicio, fim, duracao_s, revisao, registrado_em) VALUES (@execucao_id, @fonte, @status, "
           "@etapa_falha, @codigo_saida, TIMESTAMP(@inicio), TIMESTAMP(@fim), @duracao_s, "
           "@revisao, CURRENT_TIMESTAMP())")
    P = sdk.ScalarQueryParameter
    for r in resultados:
        params = [P("execucao_id", "STRING", execucao_id), P("fonte", "STRING", r["fonte"]),
                  P("status", "STRING", r["status"]), P("etapa_falha", "STRING", r["etapa_falha"]),
                  P("codigo_saida", "INT64", r["codigo_saida"]),
                  P("inicio", "STRING", r["inicio"]), P("fim", "STRING", r["fim"]),
                  P("duracao_s", "FLOAT64", r["duracao_s"]), P("revisao", "STRING", revisao)]
        cfg = sdk.QueryJobConfig(query_parameters=params, maximum_bytes_billed=100_000_000)
        cliente.query(sql, job_config=cfg).result()
    return len(resultados)


def main(argv=None, *, env=None, runner=subprocess.run, registrar=registrar_saude,
         consultar_ultimas=ultimas_execucoes_ok, agora=lambda: datetime.now(timezone.utc)):
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(description="NIVON coletor (Cloud Run Job)")
    p.add_argument("--fontes", default=env.get("NIVON_COLETOR_FONTES", ",".join(FONTES)))
    p.add_argument("--plano", action="store_true", help="só lista as etapas, sem rede")
    p.add_argument("--forcar", action="store_true", help="ignora o intervalo de cada fonte")
    a = p.parse_args(argv)
    nomes = [f.strip() for f in a.fontes.split(",") if f.strip()]
    if not nomes or len(set(nomes)) != len(nomes) or any(n not in FONTES for n in nomes):
        raise SystemExit("FONTES_INVALIDAS:" + a.fontes)
    projeto = env.get("NIVON_BQ_PROJECT", "")
    dataset, bucket = env.get("NIVON_BQ_DATASET", ""), env.get("NIVON_GCS_BUCKET", "")
    with tempfile.TemporaryDirectory(prefix="nivon-coletor-") as tmp:
        ctx = Contexto(projeto, dataset, bucket, Path(tmp), datetime.now(timezone.utc).year)
        if a.plano:
            for n in nomes:
                print(json.dumps({"fonte": n, "etapas": [c[2:] for c in FONTES[n].etapas(ctx)]},
                                 default=str))
            return 0
        if env.get("NIVON_COLETOR_HABILITADO") != "true":
            print("COLETOR_NAO_HABILITADO: defina NIVON_COLETOR_HABILITADO=true no job")
            return 3
        if projeto != PROJETO_ESPERADO or not dataset or not bucket:
            print("DESTINO_INVALIDO: NIVON_BQ_PROJECT/NIVON_BQ_DATASET/NIVON_GCS_BUCKET")
            return 3
        execucao_id = env.get("CLOUD_RUN_EXECUTION") or datetime.now(timezone.utc).strftime(
            "local-%Y%m%dT%H%M%SZ")
        if not EXECUCAO.fullmatch(execucao_id):
            return 3
        vencidas = nomes
        if not a.forcar:
            try:
                vencidas = fontes_vencidas(nomes, consultar_ultimas(projeto), agora())
            except Exception as exc:  # consulta indisponível nunca bloqueia a coleta
                print(json.dumps({"aviso": "SAUDE_INDISPONIVEL_RODANDO_TODAS",
                                  "erro": type(exc).__name__}))
        resultados = [executar_fonte(FONTES[n], ctx, runner=runner) for n in vencidas]
        print(json.dumps({"puladas_nao_vencidas": [n for n in nomes if n not in vencidas]}))
        if not resultados:
            return 0
    registrar(resultados, execucao_id=execucao_id, revisao=env.get("NIVON_REVISAO", "desconhecida"),
              projeto=projeto)
    print(json.dumps({"execucao_id": execucao_id, "resultados": resultados}))
    return 0 if all(r["status"] == "OK" for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
