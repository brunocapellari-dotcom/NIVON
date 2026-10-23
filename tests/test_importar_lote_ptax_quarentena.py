"""E2E batch PTAX: dois documentos externos, rollback e quarentena."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone

from scripts.importar_lote_ptax_quarentena import (
    importar_lote_ptax_quarentena, main, ErroLoteQuarentenaPTAX, VERSAO,
)
from nivon.ptax_quarentena_coleta import listar_amostras_ptax
from nivon.ptax_plano import planejar_consultas_ptax
from nivon.registro_snapshots import abrir_registro


def montar(pasta: Path, *, danificar_segundo=False):
    jobs=[]
    for i,d in enumerate(("2026-10-19","2026-10-20")):
        plano=planejar_consultas_ptax(
            moeda="USD",inicio=d,fim=d,
        )[0]
        raw=(b'{"value":[]}' if i==0 else (
            b'{"value":[{"cotacaoCompra":5.1000,"cotacaoVenda":5.2000,'
            b'"dataHoraCotacao":"2026-10-20 13:00:00"}]}'))
        name=f"odata_{i}.json"
        source=f"manifesto_{i}.json"
        (pasta/name).write_bytes(raw)
        meta={
            "moeda":"USD", "consulta_url":plano["url"],
            "coletado_em":"2026-10-21T18:00:00+00:00",
            "status_http":200,
            "cabecalhos_http":{
                "Content-Type":"application/json",
                "Content-Length":str(len(raw))
            },
            "raw_sha256":sha256(raw).hexdigest(),
            "fonte_declarada":"BCB_PTAX",
        }
        if i==1 and danificar_segundo:
            meta["raw_sha256"]="0"*64
        (pasta/source).write_text(json.dumps(meta),encoding="utf-8")
        jobs.append({"raw":name,"manifesto":source})
    return {"versao":VERSAO,"capturas":jobs}


class TestImportacaoLoteQuarentenaPTAX(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta=Path(self.temp.name)
        self.db=abrir_registro(":memory:")
        self.addCleanup(self.db.close)

    def test_lote_integro_e_repetido_sem_duplicar(self):
        lote=montar(self.pasta)
        r=importar_lote_ptax_quarentena(
            self.db,pasta=self.pasta,lote=lote,
        )
        self.assertEqual(r["status"],"LOTE_PTAX_QUARENTENA_RECEBIDO_SEM_PUBLICACAO")
        self.assertEqual(r["itens_processados"],2)
        self.assertEqual(r["eventos_novos"],2)
        self.assertEqual(r["respostas_vazias"],1)
        self.assertEqual(r["boletins_verificados"],1)
        self.assertFalse(r["ledger_operacional_modificado"])
        self.assertFalse(r["publicavel"])
        again=importar_lote_ptax_quarentena(
            self.db,pasta=self.pasta,lote=lote,
        )
        self.assertEqual(again["eventos_novos"],0)
        self.assertEqual(len(listar_amostras_ptax(self.db)),2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM nivon_snapshots").fetchone()[0],0)

    def test_segundo_documento_invalido_impede_todo_lote(self):
        lote=montar(self.pasta,danificar_segundo=True)
        with self.assertRaises(ErroLoteQuarentenaPTAX):
            importar_lote_ptax_quarentena(
                self.db,pasta=self.pasta,lote=lote,
            )
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='nivon_ptax_quarentena_raw'").fetchone())

    def test_desfaz_gravacao_em_transacao_externa(self):
        lote=montar(self.pasta)
        self.db.execute("SAVEPOINT externo")
        importar_lote_ptax_quarentena(
            self.db,pasta=self.pasta,lote=lote,
        )
        self.db.execute("ROLLBACK TO SAVEPOINT externo")
        self.db.execute("RELEASE SAVEPOINT externo")
        self.assertIsNone(self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='nivon_ptax_quarentena_eventos'").fetchone())

    def test_rejeita_caminhos_e_repeticoes(self):
        lote=montar(self.pasta)
        for invalido in (
            {"versao":VERSAO,"capturas":[]},
            {"versao":"INDEFINIDO","capturas":lote["capturas"]},
            {"versao":VERSAO,"capturas":lote["capturas"]*51},
            {"versao":VERSAO,"capturas":[lote["capturas"][0]]*2},
            {"versao":VERSAO,"capturas":[{
                "raw":"../segredo.json","manifesto":"manifesto_0.json"
            }]},
            {"versao":VERSAO,"capturas":[{
                "raw":"https://exemplo.org/a.json","manifesto":"manifesto_0.json"
            }]},
        ):
            with self.subTest(invalido=invalido),self.assertRaises(ErroLoteQuarentenaPTAX):
                importar_lote_ptax_quarentena(
                    self.db,pasta=self.pasta,lote=invalido,
                )

    def test_cli_uma_rodada_importa_todos(self):
        lote=montar(self.pasta)
        (self.pasta/"lote.json").write_text(json.dumps(lote),encoding="utf-8")
        output=main([
            "--pasta",str(self.pasta),"--lote","lote.json",
            "--banco",str(self.pasta/"quarentena.db")
        ])
        self.assertEqual(output["itens_processados"],2)
        with sqlite3.connect(self.pasta/"quarentena.db") as conn:
            self.assertEqual(len(listar_amostras_ptax(conn)),2)

    def test_link_simbolico_rejeitado(self):
        lote=montar(self.pasta)
        (self.pasta/"atalho.json").symlink_to(self.pasta/"odata_0.json")
        lote["capturas"][0]["raw"]="atalho.json"
        with self.assertRaises(ErroLoteQuarentenaPTAX):
            importar_lote_ptax_quarentena(
                self.db,pasta=self.pasta,lote=lote,
            )


if __name__=="__main__":
    unittest.main()
