"""Comprova que contingencia do CKAN so usa referencias com SHA ja observado."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nivon.antt_historico_verificado import DADOS, referencia_antt_verificada
from nivon.coleta_antt import CATALOGO, coletar
from nivon.transporte_multimodal import ErroTransporte


class Resposta:
    status = 200
    def __init__(self,raw): self.raw=raw
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def read(self,limite): return self.raw[:limite]


class HTMLIndisponivel:
    def __init__(self,raw=b"Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;Estacao_Destino;UF_Destino;TU;TKU\n01_21;RMO;Soja;Rondonopolis;MT;Santos;SP;120;900\n"):
        self.raw=raw
        self.calls=[]
    def open(self,req,timeout):
        self.calls.append(req.full_url)
        if req.full_url==CATALOGO:
            return Resposta(b"<html>Temporariamente indisponivel</html>")
        if req.full_url==DADOS[2021]["url"]:
            return Resposta(self.raw)
        raise AssertionError("URL externa ou nao autorizada")


class HistoricoTestes(unittest.TestCase):
    def test_dezenove_referencias_preservadas_e_sha_bq_conhecido(self):
        self.assertEqual(len(DADOS),19)
        self.assertEqual(set(DADOS),set(range(2006,2025)))
        self.assertEqual(DADOS[2022]["sha_anterior"],
                         "2771a886016599a0c9988acf089cba4f9c7a0758c6d7092390ac601bec58426a")
        for ano,registro in DADOS.items():
            self.assertEqual(registro["url"],referencia_antt_verificada(ano)["url"])
            self.assertIn(f"producao_origem_destino_{ano}.csv",registro["url"])

    def test_nao_aceita_ano_que_nunca_foi_observado(self):
        for a in (2005,2025,2100):
            with self.assertRaisesRegex(ErroTransporte,"sem URL/SHA historico validado"):
                referencia_antt_verificada(a)

    def test_com_ckan_html_e_csv_2021_alterado_sha_fechado(self):
        with tempfile.TemporaryDirectory() as pasta:
            cliente=HTMLIndisponivel()
            with patch("nivon.coleta_antt.time.sleep",return_value=None):
                with self.assertRaisesRegex(ErroTransporte,"ANTT_SHA_DIVERGENTE_SEM_CKAN_ATUAL"):
                    coletar(destino=pasta,anos=[2021],habilitar_rede=True,
                           transporte=cliente,
                           permitir_url_verificada_contingencia=True)
            self.assertFalse(Path(pasta,"manifesto-antt.json").exists())
            self.assertEqual(cliente.calls.count(DADOS[2021]["url"]),1)

    def test_sem_optin_nao_usa_url_historica(self):
        with tempfile.TemporaryDirectory() as pasta:
            cliente=HTMLIndisponivel()
            with patch("nivon.coleta_antt.time.sleep",return_value=None):
                with self.assertRaisesRegex(ErroTransporte,"catalogo CKAN invalido"):
                    coletar(destino=pasta,anos=[2021],habilitar_rede=True,
                           transporte=cliente)
            self.assertNotIn(DADOS[2021]["url"],cliente.calls)

if __name__ == "__main__":
    unittest.main()
