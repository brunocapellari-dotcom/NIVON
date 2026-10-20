import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from scripts.importar_antaq_historico import main


def zipar(d):
    b=io.BytesIO()
    with ZipFile(b,"w") as z:
        for name,content in d.items():
            z.writestr(name,content.encode("utf-8"))
    return b.getvalue()


class TestImportarAntaqCLI(unittest.TestCase):
    def test_importar_criar_banco_e_idempotencia(self):
        with TemporaryDirectory() as root:
            base=Path(root)
            annual=base/"2026.zip"
            merc=base/"Mercadoria.zip"
            db=base/"antaq.sqlite"
            annual.write_bytes(zipar({
                "2026Atracacao.txt":
                    "IDAtracacao;Porto Atracação;Terminal;Data Atracação;Ano;Mes;SGUF\n"
                    "1;Santarém;T1;15/10/2026 12:00:00;2026;10;PA\n",
                "2026Carga.txt":
                    "IDCarga;IDAtracacao;CDMercadoria;Sentido;VLPesoCargaBruta\n"
                    "2;1;3;Embarcados;1000,50\n"
            }))
            merc.write_bytes(zipar({
                "Mercadoria.txt":
                    "CDMercadoria;Nomenclatura Simplificada Mercadoria\n3;MILHO\n"
            }))
            arg=["--ano","2026","--anual",str(annual),"--mercadorias",str(merc),
                 "--banco",str(db),"--coletado-em","2026-10-19T20:00:00-03:00"]
            stdout=io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(arg),0)
            data=json.loads(stdout.getvalue())
            self.assertEqual(data["cargas"],1)
            self.assertTrue(db.exists())
            with sqlite3.connect(db) as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM antaq_edicoes").fetchone()[0],1)
            stdout=io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(arg),0)
            self.assertEqual(json.loads(stdout.getvalue())["estado"],"EDICAO_JA_IMPORTADA")

    def test_nao_criar_banco_em_symlink(self):
        with TemporaryDirectory() as root:
            p=Path(root)
            (p/"real.sqlite").touch()
            try:
                (p/"symlink.sqlite").symlink_to(p/"real.sqlite")
            except (OSError,NotImplementedError):
                self.skipTest("sistema não suporta symlink")
            with self.assertRaises(ValueError):
                main(["--ano","2026","--anual","a.zip","--mercadorias","b.zip",
                      "--banco",str(p/"symlink.sqlite"),
                      "--coletado-em","2026-10-19T20:00:00-03:00"])


if __name__=="__main__":
    unittest.main()
