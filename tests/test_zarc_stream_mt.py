"""Teste E2E offline do ZARC integral, sem arquivos externos ou rede."""
import csv
import hashlib
import io
import unittest
from datetime import datetime, timezone

from nivon.zarc_stream_mt import (
    COLUNAS, DEC, MAX_DOWNLOAD, URL, ErroZarcStream,
    _analisar_arquivo, processar_zarc_mt,
)

DATA = datetime(2026, 10, 21, 20, tzinfo=timezone.utc)

def linha(*, uf="MT", cultura="Soja", ibge="5105259", portaria="Portaria 1"):
    d = {k: "A" for k in COLUNAS}
    d.update({"UF": uf, "Nome_cultura": cultura, "geocodigo": ibge,
              "SafraIni": "2026", "SafraFin": "2027",
              "Portaria": portaria})
    d.update({k: "1" for k in DEC})
    return d

def amostra(*records):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=COLUNAS, delimiter=";", lineterminator="\n")
    w.writeheader()
    for row in records:
        w.writerow(row)
    return out.getvalue().encode("utf-8-sig")

class Resp:
    status=200
    def __init__(self, data, *, mime="text/csv", url=URL, declared=None):
        self.data = io.BytesIO(data)
        self.url = url
        self.headers = {"Content-Type": mime}
        if declared is not None:
            self.headers["Content-Length"] = declared
    def read(self, n):
        return self.data.read(n)
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *args): return False

class Client:
    def __init__(self, resp):
        self.resp, self.count=resp,0
    def open(self, req, timeout=90):
        self.count+=1
        if req.full_url != URL:
            raise AssertionError("URL fora da whitelist")
        return self.resp

class ZarcStreamTest(unittest.TestCase):
    def test_rede_default_off(self):
        with self.assertRaises(PermissionError):
            processar_zarc_mt()

    def test_duas_culturas_mt_sem_equivaler_a_risco(self):
        body=amostra(linha(),linha(uf="GO"),linha(cultura="Milho", ibge="5107925"))
        c=Client(Resp(body, declared=str(len(body))))
        d=processar_zarc_mt(executar=True, abridor=c, instante=DATA)
        self.assertEqual(c.count,1)
        self.assertEqual(d["sha256_original"], hashlib.sha256(body).hexdigest())
        self.assertEqual(d["linhas_total_arquivo"],3)
        self.assertEqual(d["linhas_mt"],2)
        self.assertEqual(d["municipios_ibge_mt"],2)
        self.assertEqual(d["linhas_por_cultura_nome_original"],{"Milho":1,"Soja":1})
        self.assertEqual(d["portarias_distintas_mt"],1)
        self.assertEqual(d["codigos_decendiais_brutos_diferentes"],1)
        self.assertFalse(d["valores_decendiais_interpretados"])
        self.assertFalse(d["persistido"])
        self.assertFalse(d["publicavel"])
        self.assertEqual(d["competencia"],"2026/2027")

    def test_safra_errada_mt_bloqueia(self):
        bad=linha()
        bad["SafraFin"]="2028"
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True, abridor=Client(Resp(amostra(bad))),
                              instante=DATA)

    def test_geocodigo_nao_ibge_bloqueia(self):
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True, abridor=Client(Resp(
                amostra(linha(ibge="123")))), instante=DATA)

    def test_coluna_diferente_bloqueia(self):
        body=amostra(linha()).replace(b"dec36",b"dec99")
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True, abridor=Client(Resp(body)),
                              instante=DATA)

    def test_csv_desalinhado_bloqueia(self):
        body=amostra(linha())+b"MT;Soja\n"
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True, abridor=Client(Resp(body)),
                              instante=DATA)

    def test_limite_transferencia_sem_baixar_bytes(self):
        b=amostra(linha())
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,
                abridor=Client(Resp(b, declared="999999999")),
                instante=DATA, max_download=4096)
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,
                abridor=Client(Resp(b"q"*4200)),instante=DATA,
                max_download=4096)
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,
                abridor=Client(Resp(b"ok")),instante=DATA,
                max_download=MAX_DOWNLOAD+1)

    def test_mime_html_e_redirect_bloqueados(self):
        b=amostra(linha())
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,
                abridor=Client(Resp(b,mime="text/html")),instante=DATA)
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,
                abridor=Client(Resp(b,url="https://example.com/arquivo.csv")),
                instante=DATA)

    def test_data_UTC_exigida(self):
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,instante=datetime(2026,10,21))

    def test_invalidacao_antes_resultado_sem_mt(self):
        with self.assertRaises(ErroZarcStream):
            processar_zarc_mt(executar=True,
                abridor=Client(Resp(amostra(linha(uf="GO")))),instante=DATA)

if __name__ == "__main__":
    unittest.main()
