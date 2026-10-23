"""Contrato SSRF da coleta GCP: DNS misto bloqueado e IP TLS fixado."""
from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from nivon.coleta_web import (
    ErroAquisicao, FonteWeb, adquirir_fonte, _ConexaoHTTPSFixada,
    _HTTPSHandlerFixado, _ip_publico_resolvido,
)

URL="https://dados.example.org/ptax?@dataInicial='10-22-2026'"
FONTE=FonteWeb(
    fonte_id="BCB_PTAX",url=URL,dominio_autorizado="dados.example.org",
    formato="JSON",status_direitos="APROVADA",
    operacoes_permitidas=frozenset({"COLETA"}))


def resolver(*ips):
    def consulta(host,port,**kwargs):
        assert host=="dados.example.org" and port==443
        return [
            (socket.AF_INET6 if ":" in ip else socket.AF_INET,
             socket.SOCK_STREAM,0,"",
             (ip,443,0,0) if ":" in ip else (ip,443))
            for ip in ips]
    return consulta


class Resposta:
    status=200
    headers={"Content-Type":"application/json"}
    def geturl(self): return URL
    def read(self,n): return b'{"ok":true}'[:n]
    def __enter__(self): return self
    def __exit__(self,*args): return False


class Abridor:
    def __init__(self): self.chamadas=0
    def open(self,req,timeout): self.chamadas+=1; return Resposta()


class TestColetaSegura(unittest.TestCase):
    def test_ip_privado_bloqueado_sem_socket(self):
        with (patch("nivon.coleta_web.socket.getaddrinfo",side_effect=resolver("169.254.169.254")),
              patch("nivon.coleta_web.socket.create_connection") as sock):
            with self.assertRaises(ErroAquisicao):
                adquirir_fonte(FONTE)
            sock.assert_not_called()

    def test_resposta_mista_e_dns_vazio_sao_bloqueados(self):
        for ips in ((),("1.1.1.1","127.0.0.1"),
                    ("2606:4700:4700::1111","fd00::1")):
            with self.subTest(ips=ips):
                with self.assertRaises(ErroAquisicao):
                    _ip_publico_resolvido("dados.example.org",resolver=resolver(*ips))

    def test_odata_query_arroba_permitido_sem_usuario(self):
        FONTE.verificar()
        abridor=Abridor()
        r=adquirir_fonte(FONTE,abridor=abridor,resolver=resolver("1.1.1.1"))
        self.assertEqual(r["conteudo"],b'{"ok":true}')
        self.assertEqual(abridor.chamadas,1)

    def test_default_usa_handler_fixado_sem_proxy(self):
        abridor=Abridor()
        with (patch("nivon.coleta_web.socket.getaddrinfo",
                    side_effect=resolver("1.1.1.1")),
              patch("nivon.coleta_web.build_opener",return_value=abridor) as opener):
            adquirir_fonte(FONTE)
        self.assertEqual(abridor.chamadas,1)
        tipos=[type(x).__name__ for x in opener.call_args.args]
        self.assertIn("_HTTPSHandlerFixado",tipos)
        self.assertIn("ProxyHandler",tipos)
        transport=next(x for x in opener.call_args.args
                       if isinstance(x,_HTTPSHandlerFixado))
        self.assertEqual(transport._ip_fixo,"1.1.1.1")

    def test_sni_do_hostname_com_socket_ip_fixado(self):
        class Socket:
            def close(self): pass
        class Context:
            sni=None
            def wrap_socket(self,sock,server_hostname):
                self.sni=server_hostname
                return sock
        sock=Socket();context=Context()
        conn=_ConexaoHTTPSFixada("dados.example.org",ip_fixo="1.1.1.1",timeout=2)
        conn._context=context
        with patch("nivon.coleta_web.socket.create_connection",return_value=sock) as chamada:
            conn.connect()
        self.assertEqual(chamada.call_args.args[0],("1.1.1.1",443))
        self.assertEqual(context.sni,"dados.example.org")
        self.assertIs(conn.sock,sock)
        conn.close()

    def test_url_com_controle_rejeitada(self):
        for url in ("https://dados.example.org:abc/",URL+"\rX:evil",
                    "https://user:pass@dados.example.org/ptax",
                    "https://metadata.google.internal/latest"):
            fonte=FonteWeb(
                fonte_id="BCB_PTAX",url=url,
                dominio_autorizado="metadata.google.internal"
                    if "metadata" in url else "dados.example.org",
                formato="JSON",status_direitos="APROVADA",
                operacoes_permitidas=frozenset({"COLETA"}))
            with self.subTest(url=url):
                with self.assertRaises(ErroAquisicao):
                    fonte.verificar()


if __name__=="__main__":
    unittest.main()
