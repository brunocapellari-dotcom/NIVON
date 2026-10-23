"""Integração de progresso Drive: CSV offline -> série -> auditoria temporal.

Fixtures inventadas: o arquivo real do Drive foi examinado pelo conector,
mas nunca é embutido ou tratado como vintage oficial neste teste.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
from unittest import TestCase
from nivon.conab_progresso_csv_drive import normalizar_csv_progresso_conab
from nivon.conab_progresso_auditoria import (
    auditar_progresso_conab_drive, ErroAuditoriaProgresso,
)

HEADER=",Data,Semana,Mês,Ano,Estado,Semeadura / Colheita,Produto,Dado,INFO"
ROWS=[
    "0,2019-11-08 00:00:00,45,Novembro,2019,Bahia,Semeadura,Soja,0.75,Brasil",
    "1,2019-11-15 00:00:00,46,Novembro,2019,Bahia,Semeadura,Soja,0.85,Brasil",
    "2,2020-07-03 00:00:00,27,Julho,2020,Bahia,Semeadura,Soja,0.10,Brasil",
    "3,2020-07-10 00:00:00,28,Julho,2020,Bahia,Semeadura,Soja,0.15,Brasil",
]
def _raw():
    return (HEADER+"\n"+"\n".join(ROWS)+"\n").encode("utf-8")
def _norm():
    v=_raw()
    return normalizar_csv_progresso_conab(
        raw_csv=v,sha256_esperado=sha256(v).hexdigest(),
        adquirido_em="2026-10-23T11:00:00-04:00"
    )


class TestAuditoriaTemporalProgresso(TestCase):
    def test_avanco_e_reinicio_nao_sao_tendencia(self):
        result=auditar_progresso_conab_drive(normalizado=_norm())
        self.assertEqual(result["total_registros"],4)
        self.assertEqual(result["grupos_uf_operacao_produto"],1)
        self.assertEqual(result["intervalos_superiores_60_dias"],1)
        self.assertEqual(result["reducoes_de_fracao_sem_ciclo_validado"],1)
        self.assertEqual(result["reducoes_de_25pp_ou_mais_sem_ciclo_validado"],1)
        event=next(x for x in result["eventos_amostrados"]
                   if "PERCENTUAL_MENOR_SEM_SAFRA_IDENTIFICADA" in x["eventos"])
        self.assertFalse(event["erro_confirmado"])
        self.assertFalse(event["troca_safra_confirmada"])
        self.assertFalse(result["safras_ano_ciclo_identificadas"])
        self.assertFalse(result["habilita_backtest"])
        self.assertFalse(result["habilita_publicacao"])

    def test_manipulacao_vintage_reprovada(self):
        doc=_norm()
        doc["registros"][0]["disponivel_em"]="2019-11-08T12:00:00Z"
        with self.assertRaisesRegex(ErroAuditoriaProgresso,"vintage"):
            auditar_progresso_conab_drive(normalizado=doc)

    def test_manipulacao_hash_reprovada(self):
        doc=_norm()
        doc["registros"][0]["fonte_raw_sha256"]="a"*64
        with self.assertRaisesRegex(ErroAuditoriaProgresso,"SHA"):
            auditar_progresso_conab_drive(normalizado=doc)

    def test_mesmo_recorte_repetido_reprovado(self):
        doc=_norm()
        doc["registros"].append(dict(doc["registros"][0]))
        doc["total"]+=1
        with self.assertRaisesRegex(ErroAuditoriaProgresso,"repetida"):
            auditar_progresso_conab_drive(normalizado=doc)

    def test_cli_uma_chamada_gera_historico_e_qa(self):
        with tempfile.TemporaryDirectory() as td:
            dest=Path(td)
            raw=dest/"original.csv"
            out=dest/"normalizado.json"
            qa=dest/"auditoria.json"
            raw.write_bytes(_raw())
            project=Path(__file__).resolve().parents[1]
            env=os.environ.copy()
            env["PYTHONPATH"]=str(project/"src")+os.pathsep+env.get("PYTHONPATH","")
            cmd=[
                sys.executable,"-m","nivon.conab_progresso_csv_drive",
                "--input",str(raw),"--sha256",sha256(_raw()).hexdigest(),
                "--adquirido-em","2026-10-23T11:00:00-04:00",
                "--out",str(out),"--auditoria-out",str(qa)
            ]
            p=subprocess.run(cmd,env=env,cwd=project,text=True,
                             capture_output=True,timeout=25)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertEqual(json.loads(out.read_text())["total"],4)
            summary=json.loads(qa.read_text())
            self.assertEqual(summary["reducoes_de_fracao_sem_ciclo_validado"],1)
            self.assertFalse(summary["habilita_treino"])
            repeated=subprocess.run(cmd,env=env,cwd=project,text=True,
                                    capture_output=True,timeout=25)
            self.assertEqual(repeated.returncode,3)
            self.assertEqual(json.loads(qa.read_text())["total_registros"],4)


if __name__=="__main__":
    import unittest
    unittest.main()
