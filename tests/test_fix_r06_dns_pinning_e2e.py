"""Regressão R06: DNS privado/misto e socket HTTPS fixado sem rede real.

Resolução, socket, TLS e resposta HTTP são todos objetos sintéticos.
O teste não habilita coleta comercial, não acessa APIs nem credenciais.
"""
from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from nivon.coleta_web import (
    ErroAquisicao, FonteWeb, adquirir_fonte, _ConexaoHTTPSFixada,
    _ip_publico_resolvido,
)

URL = "https://porto.example.org/documento.html"
FONTE = FonteWeb(
    "PORTO_FICTICIO", URL, "porto.example.org", "HTML", "APROVADA",
    frozenset({"COLETA"}),
)


def resolver_fake(*ips):
    def resolver(host, port, **kw):
        assert host == "porto.example.org"
        assert port == 443
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET,
             socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
             (ip, 443, 0, 0) if ":" in ip else (ip, 443))
            for ip in ips
        ]
    return resolver


class AbridorDeTeste:
    chamadas = 0

    def open(self, req, timeout):
        self.chamadas += 1
        class Resposta:
            status = 200
            headers = {"Content-Type": "text/html"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
            def geturl(self):
                return URL
            def read(self, tamanho):
                return b"<html>teste</html>"[:tamanho]
        return Resposta()


class TestDNSControladoR06(unittest.TestCase):
    def test_bloqueia_oito_enderecos_privados_antes_de_http(self):
        for ip in (
            "127.0.0.1", "10.2.3.4", "172.16.0.5", "192.168.1.20",
            "169.254.169.254", "::1", "fd00::55", "fe80::1",
        ):
            with self.subTest(ip=ip):
                abridor = AbridorDeTeste()
                with self.assertRaisesRegex(ErroAquisicao, "não pública"):
                    adquirir_fonte(
                        FONTE, abridor=abridor, resolver=resolver_fake(ip)
                    )
                self.assertEqual(abridor.chamadas, 0)

    def test_resposta_mista_publica_privada_recusada(self):
        for ips in (
            ("1.1.1.1", "127.0.0.1"),
            ("1.1.1.1", "169.254.169.254"),
            ("2606:4700:4700::1111", "fd00::1"),
        ):
            with self.subTest(ips=ips):
                abridor = AbridorDeTeste()
                with self.assertRaises(ErroAquisicao):
                    adquirir_fonte(
                        FONTE, abridor=abridor, resolver=resolver_fake(*ips)
                    )
                self.assertEqual(abridor.chamadas, 0)

    def test_dados_sinteticos_somente_arquivo_nao_operacional(self):
        abridor = AbridorDeTeste()
        r = adquirir_fonte(
            FONTE, abridor=abridor,
            resolver=resolver_fake("1.1.1.1"),
        )
        self.assertEqual(abridor.chamadas, 1)
        self.assertEqual(
            r["classificacao"],
            "ARQUIVO_COLETADO_NAO_EQUIVALE_DADO_OPERACIONAL_VALIDADO",
        )

    def test_default_nega_dns_privado_antes_de_socket(self):
        with (
            patch("socket.getaddrinfo", side_effect=resolver_fake("127.0.0.1")),
            patch("socket.create_connection", side_effect=AssertionError(
                "socket não pode ser criado para IP privado"
            )),
        ):
            with self.assertRaises(ErroAquisicao):
                adquirir_fonte(FONTE)

    def test_dns_vazio_recusado(self):
        with self.assertRaises(ErroAquisicao):
            _ip_publico_resolvido("porto.example.org", resolver=resolver_fake())

    def test_conexao_pinned_usa_sni_do_dominio_e_ip_auditado(self):
        class SocketTeste:
            fechado = False
            def close(self):
                self.fechado = True

        class ContextoTLS:
            def __init__(self):
                self.sni = None
            def wrap_socket(self, sock, *, server_hostname):
                self.sni = server_hostname
                return sock

        fake = SocketTeste()
        ctx = ContextoTLS()
        conn = _ConexaoHTTPSFixada(
            "porto.example.org", ip_fixo="1.1.1.1", timeout=2,
        )
        conn._context = ctx
        with patch("socket.create_connection", return_value=fake) as called:
            conn.connect()
        self.assertEqual(called.call_args.args[0], ("1.1.1.1", 443))
        self.assertEqual(ctx.sni, "porto.example.org")
        self.assertIs(conn.sock, fake)
        conn.close()


if __name__ == "__main__":
    unittest.main()
