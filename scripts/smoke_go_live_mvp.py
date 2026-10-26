#!/usr/bin/env python3
"""Smoke do produto web real: servidor HTTP local + IVO + gates de edição.

Nenhuma rede externa, GCP, token, dado oficial ou release real nesta prova.
"""
import hashlib
import json
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from nivon.mvp_server import _handler


def http(port, path, *, body=None):
    req = Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"} if body else {},
    )
    try:
        with urlopen(req, timeout=3) as response:
            return response.status, response.read().decode()
    except HTTPError as exc:
        return exc.code, exc.read().decode()


def main():
    with tempfile.TemporaryDirectory() as work:
        path = Path(work) / "edicao.json"
        cfg = {}
        server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(cfg))
        thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        thread.start()
        try:
            status, body = http(server.server_port, "/healthz")
            assert status == 200 and json.loads(body)["status"] == "PROCESSO_ATIVO"
            status, body = http(server.server_port, "/api/edicao")
            assert status == 503 and not json.loads(body)["edicao_liberada"]
            data = urlencode({
                "pergunta": "Analisar soja, clima e frete em Mato Grosso",
            }).encode("utf-8")
            status, body = http(server.server_port, "/ivo", body=data)
            assert status == 200 and "PLANO_OFFLINE_SEM_DADOS_HOMOLOGADOS" in body
            assert "SOJA" in body and "FRETE_RODOVIARIO" in body

            now = datetime.now(timezone.utc)
            edition = {
                "schema": "nivon_mvp_edicao_v1",
                "edicao": "EDICAO-EXCLUSIVA-CI",
                "gerado_em": now.isoformat(),
                "fontes": {"FONTE_SINTETICA": {
                    "status_direitos": "APROVADA",
                    "operacoes": ["LEITURA", "RESUMO", "PUBLICACAO_DERIVADA"],
                }},
                "noticias": [],
                "indicadores": [{
                    "fonte_id": "FONTE_SINTETICA",
                    "secao": "CAMBIO",
                    "titulo": "Exemplo não observado",
                    "valor": "R$ 1,00 — SINTÉTICO",
                    "referencia": (now-timedelta(hours=1)).isoformat(),
                    "fonte": "Fixture sintética CI",
                }],
                "fretes": [],
            }
            raw = json.dumps(edition, ensure_ascii=False).encode("utf-8")
            path.write_bytes(raw)
            cfg.update({
                "NIVON_RELEASE_APPROVED": "true",
                "NIVON_RELEASE_FILE": str(path),
                "NIVON_RELEASE_SHA256": hashlib.sha256(raw).hexdigest(),
            })
            status, body = http(server.server_port, "/api/edicao")
            assert status == 200
            pack = json.loads(body)
            assert pack["indicadores_incluidos"] == 1
            assert not pack["envio_whatsapp_realizado"]
            assert not pack["licencas_externas_atestadas_por_este_servico"]
            path.write_bytes(b'{"tampered":true}')
            status, body = http(server.server_port, "/api/edicao")
            assert status == 503
            assert not json.loads(body)["edicao_liberada"]
            print(json.dumps({
                "estado": "MVP_HTTP_CI_SUCESSO",
                "routes_ok": ["/healthz", "/api/edicao", "/ivo"],
                "liberacao_sem_hash": False,
                "consulta_ivo_realizada": True,
                "integridade_rejeitou_adulteracao": True,
                "rede_externa": False,
                "edicao_real_publicada": False,
                "deploy_cloud": False,
                "envio_whatsapp": False,
            }, ensure_ascii=False, sort_keys=True))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
