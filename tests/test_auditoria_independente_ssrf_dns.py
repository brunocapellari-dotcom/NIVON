"""Auditoria adversarial do DNS/egress do coletor R06.

Nenhuma resolução DNS real nem HTTP é efetuada. Toda resposta DNS e HTTP
é simulada; estes testes são gates de risco, não ativam coleta produtiva.
"""
from __future__ import annotations

from dataclasses import replace
import socket
import unittest
from unittest.mock import patch

from nivon.coleta_web import ErroAquisicao, FonteWeb, adquirir_fonte


class _Resposta:
    status = 200
    headers = {"Content-Type": "text/html"}

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.url

    def read(self, limite):
        return b"<html>fixture R06</html>"[:limite]


class _Abridor:
    def __init__(self):
        self.chamadas = 0

    def open(self, req, timeout):
        self.chamadas += 1
        return _Resposta(req.full_url)


def _fonte(url="https://porto.example.org/lineup.html"):
    return FonteWeb(
        fonte_id="PORTO_FICTICIO_TESTE",
        url=url,
        dominio_autorizado="porto.example.org",
        formato="HTML",
        status_direitos="APROVADA",
        operacoes_permitidas=frozenset({"COLETA"}),
    )


def _dns(*ips):
    return [
        (socket.AF_INET6 if ":" in ip else socket.AF_INET,
         socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
         (ip, 443, 0, 0) if ":" in ip else (ip, 443))
        for ip in ips
    ]


class TestAuditoriaSSRFDNS(unittest.TestCase):
    def test_controle_ip_literal_privado_bloqueado_sem_http(self):
        f = replace(
            _fonte(),
            url="https://169.254.169.254/latest/meta-data/",
            dominio_autorizado="169.254.169.254",
        )
        abridor = _Abridor()
        with self.assertRaises(ErroAquisicao):
            adquirir_fonte(f, abridor=abridor)
        self.assertEqual(abridor.chamadas, 0)

    def test_controle_https_publico_com_stub_http_nao_publicavel(self):
        # Apenas URL publicamente plausível; não certifica DNS nem origem.
        abridor = _Abridor()
        resposta = adquirir_fonte(_fonte(), abridor=abridor)
        self.assertEqual(abridor.chamadas, 1)
        self.assertEqual(resposta["fonte_id"], "PORTO_FICTICIO_TESTE")
        self.assertEqual(
            resposta["classificacao"],
            "ARQUIVO_COLETADO_NAO_EQUIVALE_DADO_OPERACIONAL_VALIDADO",
        )

    def test_p0_host_aprovado_dns_privado_ou_metadata_recusado(self):
        enderecos = (
            "127.0.0.1", "10.2.3.4", "172.16.0.5",
            "192.168.1.20", "169.254.169.254",
            "::1", "fd00::55", "fe80::1",
        )
        for ip in enderecos:
            with self.subTest(endereco_resolvido=ip):
                abridor = _Abridor()
                with patch("socket.getaddrinfo", return_value=_dns(ip)):
                    with self.assertRaises(
                        ErroAquisicao,
                        msg="P0: host HTTPS nominalmente autorizado não pode "
                            "abrir recurso interno a partir do DNS privado",
                    ):
                        adquirir_fonte(_fonte(), abridor=abridor)
                self.assertEqual(
                    abridor.chamadas, 0,
                    "P0: bloqueio DNS deve ocorrer antes de usar o abridor "
                    "HTTP, inclusive com status_direitos aprovado",
                )

    def test_p0_dns_misto_publico_privado_rejeitado_integralmente(self):
        # Um retorno DNS público + privado não habilita fallback para o
        # endereço interno; check de apenas uma resposta é insuficiente.
        for ips in (
            ("203.0.113.23", "127.0.0.1"),
            ("203.0.113.23", "169.254.169.254"),
            ("2001:db8::1", "fd00::1"),
        ):
            with self.subTest(resolucao=ips):
                abridor = _Abridor()
                with patch("socket.getaddrinfo", return_value=_dns(*ips)):
                    with self.assertRaises(
                        ErroAquisicao,
                        msg="P0: qualquer endereço privado da resposta DNS "
                            "deve impedir o acesso",
                    ):
                        adquirir_fonte(_fonte(), abridor=abridor)
                self.assertEqual(abridor.chamadas, 0)


if __name__ == "__main__":
    unittest.main()
