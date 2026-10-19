import unittest
from dataclasses import replace

from nivon.coleta_web import ErroAquisicao, FonteWeb, adquirir_fonte


class RespostaFalsa:
    def __init__(self, url, conteudo=b"<html></html>", mime="text/html", status=200):
        self.url = url
        self.conteudo = conteudo
        self.status = status
        self.headers = {"Content-Type": mime, "ETag": '"fixture"'}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, tamanho):
        return self.conteudo[:tamanho]


class AbridorFalso:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = 0

    def open(self, req, timeout):
        self.chamadas += 1
        return self.resposta


class TestColetaWeb(unittest.TestCase):
    def fonte(self):
        return FonteWeb(
            "PORTO_SINTETICO",
            "https://porto.example/lineup.html",
            "porto.example", "HTML", "APROVADA",
            frozenset({"COLETA"}))

    def test_fonte_pendente_bloqueia_sem_tentar_rede(self):
        f = replace(self.fonte(), status_direitos="PENDENTE")
        stub = AbridorFalso(RespostaFalsa(f.url))
        with self.assertRaises(PermissionError):
            adquirir_fonte(f, abridor=stub)
        self.assertEqual(stub.chamadas, 0)

    def test_sem_permissao_de_coleta_bloqueia(self):
        with self.assertRaises(PermissionError):
            adquirir_fonte(replace(self.fonte(), operacoes_permitidas=frozenset()))

    def test_host_externo_bloqueado(self):
        with self.assertRaises(ErroAquisicao):
            replace(self.fonte(), url="https://evil.example/lineup.html").verificar()

    def test_url_com_usuario_ou_http_bloqueado(self):
        for url in ("http://porto.example/lineup.html",
                    "https://user:pass@porto.example/lineup.html"):
            with self.assertRaises(ErroAquisicao):
                replace(self.fonte(), url=url).verificar()

    def test_recebe_payload_com_hash_e_metadados(self):
        f = self.fonte()
        r = adquirir_fonte(f, abridor=AbridorFalso(RespostaFalsa(f.url)))
        self.assertEqual(len(r["sha256"]), 64)
        self.assertEqual(r["bytes"], len(b"<html></html>"))
        self.assertEqual(r["etag"], '"fixture"')

    def test_redirecionamento_nao_permitido(self):
        f = self.fonte()
        with self.assertRaises(ErroAquisicao):
            adquirir_fonte(f, abridor=AbridorFalso(RespostaFalsa("https://outro.example")))

    def test_mime_divergente_nao_permitido(self):
        f = self.fonte()
        with self.assertRaises(ErroAquisicao):
            adquirir_fonte(f, abridor=AbridorFalso(RespostaFalsa(f.url, mime="image/png")))

    def test_limite_bytes(self):
        f = replace(self.fonte(), limite_bytes=4)
        with self.assertRaises(ErroAquisicao):
            adquirir_fonte(f, abridor=AbridorFalso(RespostaFalsa(f.url)))

    def test_pdf_exige_assinatura_valida(self):
        f = replace(self.fonte(), formato="PDF")
        with self.assertRaises(ErroAquisicao):
            adquirir_fonte(f, abridor=AbridorFalso(RespostaFalsa(f.url, conteudo=b"xyz",
                                                               mime="application/pdf")))


    def test_json_api_somente_fonte_autorizada(self):
        f = replace(self.fonte(), formato="JSON")
        resposta = RespostaFalsa(f.url, conteudo=b'[{"id": 1}]', mime="application/json")
        r = adquirir_fonte(f, abridor=AbridorFalso(resposta))
        self.assertEqual(r["mime"], "application/json")
        self.assertEqual(r["conteudo"], b'[{"id": 1}]')

    def test_json_nao_aceita_html_de_bloqueio_waf(self):
        f = replace(self.fonte(), formato="JSON")
        resposta = RespostaFalsa(f.url, conteudo=b"<html>rejected</html>", mime="text/html")
        with self.assertRaises(ErroAquisicao):
            adquirir_fonte(f, abridor=AbridorFalso(resposta))


if __name__ == "__main__":
    unittest.main()
