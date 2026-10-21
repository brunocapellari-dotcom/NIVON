"""Regressão ZIP histórico INMET, com arquivos artificiais e sem rede."""
import io
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from nivon.inmet_historico import (
    ErroHistoricoINMET, planejar_historico,
    inspecionar_arquivo, obter_csv_em_memoria,
)


def zip_sintetico(entries):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name,content in entries:
            z.writestr(name,content)
    return buf.getvalue()


class TestHistoricoINMET(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.arquivo=Path(self.tmp.name)/"2026.zip"

    def salvar(self,entries):
        self.arquivo.write_bytes(zip_sintetico(entries))

    def test_plano_2000_ate_2026_nao_faz_download(self):
        plano=planejar_historico(ano_inicial=2024,ano_final=2026)
        self.assertEqual(len(plano),3)
        self.assertTrue(plano[-1]["arquivo_url"].endswith("/2026.zip"))
        self.assertFalse(any(x["executar"] or x["coleta_autorizada"] for x in plano))
        for inicio,fim in ((1999,2000),(2026,2027),(2025,2023)):
            with self.assertRaises(ErroHistoricoINMET):
                planejar_historico(ano_inicial=inicio,ano_final=fim)

    def test_zip_valido_so_inspeciona_sem_extrair(self):
        self.salvar([("estacoes/INMET_A801_2026.CSV",b"DATA;PRECIPITACAO\n2026-01-01;10,5\n")])
        resultado=inspecionar_arquivo(self.arquivo,ano=2026)
        self.assertEqual(resultado["arquivos_csv"],1)
        self.assertFalse(resultado["schema_homologado"])
        self.assertFalse(resultado["arquivo_extraido"])
        self.assertEqual(list(Path(self.tmp.name).iterdir()),[self.arquivo])
        self.assertIn(b"PRECIPITACAO",obter_csv_em_memoria(self.arquivo,ano=2026,
                                nome="estacoes/INMET_A801_2026.CSV"))

    def test_zip_traversal_proibido(self):
        self.salvar([("../fora.csv",b"teste")])
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(self.arquivo,ano=2026)

    def test_zip_symlink_proibido(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            item=zipfile.ZipInfo("link.csv")
            item.create_system=3
            item.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(item,b"alvo")
        self.arquivo.write_bytes(buf.getvalue())
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(self.arquivo,ano=2026)

    def test_zip_arquivos_repetidos_bloqueado(self):
        self.salvar([("a.csv",b"one"),("a.csv",b"two")])
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(self.arquivo,ano=2026)

    def test_zip_sem_csv_bloqueado(self):
        self.salvar([("README.txt",b"texto")])
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(self.arquivo,ano=2026)

    def test_zip_bomba_ratio_bloqueado(self):
        self.salvar([("zipbomb.csv",b"X"*1_000_000)])
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(self.arquivo,ano=2026)

    def test_arquivo_invalido_e_link_proibidos(self):
        self.arquivo.write_bytes(b"nao eh zip")
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(self.arquivo,ano=2026)
        self.arquivo.unlink()
        link=Path(self.tmp.name)/"link.zip"
        link.symlink_to(Path(self.tmp.name)/"nao_existe.zip")
        with self.assertRaises(ErroHistoricoINMET):
            inspecionar_arquivo(link,ano=2026)

    def test_leitura_explicita_limite(self):
        self.salvar([("a.csv",b"ABCD")])
        with self.assertRaises(ErroHistoricoINMET):
            obter_csv_em_memoria(self.arquivo,ano=2026,nome="a.csv",max_bytes=3)
        with self.assertRaises(ErroHistoricoINMET):
            obter_csv_em_memoria(self.arquivo,ano=2026,nome="../outro.csv")
        with self.assertRaises(ErroHistoricoINMET):
            obter_csv_em_memoria(self.arquivo,ano=2026,nome="a.exe")

if __name__=="__main__":
    unittest.main()
