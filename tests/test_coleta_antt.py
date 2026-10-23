import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from nivon.coleta_antt import CATALOGO, _ler_catalogo, catalogo_antt, coletar
from nivon.resumo_antt import consolidar_staging
from nivon.transporte_multimodal import ErroTransporte

PREFIX = "https://dados.antt.gov.br/dataset/438a5184-09db-49a3-88c8-0bad418b4409/resource/"
CSV_URL = PREFIX + "c2854ec9-1cc5-4554-a1ae-96c5f37b5df6/download/producao_origem_destino_2026.csv"
COLS = "Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;Estacao_Destino;UF_Destino;TU;TKU\n"
ROW = "02_26;RMO;SOJA;RON;MT;STS;SP;123,0;9999,0\n"


def catalogo(*, url=CSV_URL, revision="r1"):
    return json.dumps({"success": True, "result": {"resources": [
        {"name": "Producao Origem Destino 2026", "format": "CSV",
         "url": url, "id": "c2854ec9-1cc5-4554-a1ae-96c5f37b5df6",
         "revision_id": revision, "last_modified": "2026-10-02"}
    ]}}).encode()


class Resposta:
    status = 200

    def __init__(self, conteudo):
        self.conteudo = conteudo

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limite):
        return self.conteudo[:limite]


class Transporte:
    def __init__(self):
        self.csv_calls = 0
        self.revision = "r1"

    def open(self, req, timeout):
        if req.full_url == CATALOGO:
            return Resposta(catalogo(revision=self.revision))
        if req.full_url == CSV_URL:
            self.csv_calls += 1
            return Resposta((COLS + ROW).encode("utf-8"))
        raise AssertionError("host/recurso inesperado")


class TestCatalogo(unittest.TestCase):
    def test_licenca_e_formato_nao_implicam_rede(self):
        with self.assertRaises(PermissionError):
            catalogo_antt()
        with self.assertRaises(PermissionError):
            coletar(destino="/tmp/ignorado", anos=[2026])

    def test_descobre_ano_sem_hardcode(self):
        anos = _ler_catalogo(catalogo())
        self.assertEqual(list(anos), [2026])
        self.assertEqual(anos[2026]["url"], CSV_URL)

    def test_bloqueia_dominios_e_recursos_alheios(self):
        for url in ("https://exemplo.com/2026.csv", "http://dados.antt.gov.br/2026.csv",
                    CSV_URL + "?next=https://exemplo.com"):
            with self.subTest(url=url):
                with self.assertRaises(ErroTransporte):
                    _ler_catalogo(catalogo(url=url))

    def test_ckan_retentativa_transitoria_limitada(self):
        class Intermitente:
            def __init__(self):
                self.chamadas = 0
            def open(self, req, timeout):
                self.chamadas += 1
                if self.chamadas < 3:
                    return Resposta(b"<html>temporarily unavailable</html>")
                return Resposta(catalogo())
        cliente = Intermitente()
        pausas = []
        dados = catalogo_antt(habilitar_rede=True, transporte=cliente,
                              dormir=pausas.append)
        self.assertEqual(list(dados), [2026])
        self.assertEqual(pausas, [1, 2])
        self.assertEqual(cliente.chamadas, 3)

    def test_acesso_bloqueado_nao_faz_retry(self):
        from urllib.error import HTTPError
        class Bloqueado:
            chamadas = 0
            def open(self, req, timeout):
                self.chamadas += 1
                raise HTTPError(req.full_url, 403, "Forbidden", {}, None)
        cliente = Bloqueado()
        with self.assertRaisesRegex(ErroTransporte, "ANTT_ACESSO_BLOQUEADO"):
            catalogo_antt(habilitar_rede=True, transporte=cliente,
                          dormir=lambda x: self.fail("nao pode repetir 403"))
        self.assertEqual(cliente.chamadas, 1)

    def test_ckan_persistente_falha_com_teto(self):
        class Indisponivel:
            chamadas = 0
            def open(self, req, timeout):
                self.chamadas += 1
                return Resposta(b"<html>indisponivel</html>")
        cliente = Indisponivel()
        with self.assertRaisesRegex(ErroTransporte, "catalogo CKAN invalido"):
            catalogo_antt(habilitar_rede=True, transporte=cliente,
                          dormir=lambda _: None, max_tentativas=3)
        self.assertEqual(cliente.chamadas, 3)

    def test_rejeita_ano_duplicado(self):
        c = json.loads(catalogo())
        c["result"]["resources"].append(dict(c["result"]["resources"][0]))
        with self.assertRaises(ErroTransporte):
            _ler_catalogo(json.dumps(c).encode())


class TestColetor(unittest.TestCase):
    def test_fallback_csv_oficial_somente_opt_in_com_sha_e_proveniencia(self):
        class CatalogoHTML(Transporte):
            def open(self, req, timeout):
                if req.full_url == CATALOGO:
                    return Resposta(b"<html>Servico CKAN temporariamente invalido</html>")
                return super().open(req, timeout)
        with tempfile.TemporaryDirectory() as pasta:
            client = CatalogoHTML()
            with patch("nivon.coleta_antt.time.sleep", return_value=None):
                with self.assertRaisesRegex(ErroTransporte, "catalogo CKAN invalido"):
                    coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                           transporte=client)
                dados = coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                               transporte=client,
                               permitir_url_verificada_contingencia=True)
            self.assertEqual(dados[0]["descoberta_fonte"],
                             "URL_OFICIAL_PREVALIDADA_SEM_CKAN_ATUAL")
            self.assertEqual(dados[0]["estado"], "STAGING_NAO_HOMOLOGADO")
            self.assertEqual(client.csv_calls, 1)
            manifest=json.loads(Path(pasta, "manifesto-antt.json").read_text())
            info=manifest["anos"]["2026"]
            self.assertEqual(info["descoberta_fonte"],
                             "URL_OFICIAL_PREVALIDADA_SEM_CKAN_ATUAL")
            self.assertEqual(info["url"], CSV_URL)
            self.assertIsNone(info["revision_id"])
            self.assertEqual(info["registros"], 1)
            self.assertEqual(len(info["sha256"]), 64)

    def test_fallback_nao_permite_ano_sem_url_oficial_verificada(self):
        class CatalogoHTML(Transporte):
            def open(self, req, timeout):
                if req.full_url == CATALOGO:
                    return Resposta(b"<html>erro</html>")
                return super().open(req, timeout)
        with tempfile.TemporaryDirectory() as pasta:
            with patch("nivon.coleta_antt.time.sleep", return_value=None):
                with self.assertRaisesRegex(ErroTransporte, "sem URL CSV oficialmente verificada"):
                    coletar(destino=pasta, anos=[2024], habilitar_rede=True,
                           transporte=CatalogoHTML(),
                           permitir_url_verificada_contingencia=True)
            self.assertFalse(Path(pasta, "manifesto-antt.json").exists())

    def test_fallback_nunca_contorna_403(self):
        from urllib.error import HTTPError
        class SemAcesso(Transporte):
            def open(self, req, timeout):
                if req.full_url == CATALOGO:
                    raise HTTPError(req.full_url,403,"Proibido",{},None)
                raise AssertionError("nao tentar URL direta se CKAN bloqueado 403")
        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaisesRegex(ErroTransporte, "ANTT_ACESSO_BLOQUEADO"):
                coletar(destino=pasta,anos=[2026],habilitar_rede=True,
                       transporte=SemAcesso(),
                       permitir_url_verificada_contingencia=True)

    def test_coleta_incremental_revalidacao_e_revisao(self):
        transport = Transporte()
        inicio = datetime(2026, 10, 22, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as pasta:
            r = coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                       transporte=transport, agora=inicio)
            self.assertEqual(transport.csv_calls, 1)
            self.assertEqual(r[0]["registros"], 1)
            self.assertEqual(r[0]["competencia_maxima"], "2026-02")
            self.assertIn('"toneladas_uteis": "123.0"', Path(pasta, "antt-od-2026.jsonl").read_text())
            r = coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                       transporte=transport, agora=inicio + timedelta(days=1))
            self.assertEqual(r[0]["estado"], "SEM_REVISAO")
            self.assertEqual(transport.csv_calls, 1)
            transport.revision = "r2"
            r = coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                       transporte=transport, agora=inicio + timedelta(days=2))
            self.assertEqual(transport.csv_calls, 2)
            self.assertEqual(r[0]["estado"], "STAGING_NAO_HOMOLOGADO")
            r = coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                       transporte=transport, agora=inicio + timedelta(days=10))
            self.assertEqual(transport.csv_calls, 3)
            man = json.loads(Path(pasta, "manifesto-antt.json").read_text())
            self.assertEqual(man["anos"]["2026"]["revision_id"], "r2")
            self.assertEqual(len(man["anos"]["2026"]["sha256"]), 64)

    def test_consolidacao_preserva_tu_tku_e_mes(self):
        with tempfile.TemporaryDirectory() as pasta:
            coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                   transporte=Transporte(), agora=datetime(2026, 10, 22, tzinfo=timezone.utc))
            r = consolidar_staging(pasta, [2026])
            self.assertEqual(r["toneladas_uteis"], "123.0")
            self.assertEqual(r["tku_raw"], "9999.0")
            self.assertEqual(r["por_mes"]["2026-02"], "123.0")
            self.assertEqual(r["por_uf_origem"]["MT"], "123.0")
            self.assertEqual(r["registros"], 1)
            self.assertEqual(r["por_ano"]["2026"]["tu"], "123.0")
            self.assertEqual(r["por_ano"]["2026"]["tu_origem_mt"], "123.0")
            self.assertEqual(r["por_ano"]["2026"]["tu_soja"], "123.0")

    def test_nao_marca_arquivo_corrompido_como_recebido(self):
        class Corrompido(Transporte):
            def open(self, req, timeout):
                if req.full_url == CSV_URL:
                    return Resposta(b"invalid;csv;sem;campos\n")
                return super().open(req, timeout)

        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaises(ErroTransporte):
                coletar(destino=pasta, anos=[2026], habilitar_rede=True,
                       transporte=Corrompido())
            self.assertFalse(Path(pasta, "manifesto-antt.json").exists())


if __name__ == "__main__":
    unittest.main()
