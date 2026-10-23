"""Regressões do contrato CSV canônico (não formato oficial de bolsa)."""
import csv
from hashlib import sha256
import io
import json
import unittest

from nivon.auditoria_extracao_csv_mercados import (
    COLUNAS, CSV_PARSER_ID, CSV_PARSER_VERSAO,
    ErroExtracaoCSV, verificar_extracao_csv_canonico,
)

CORTE = "2026-10-20T12:00:00Z"
RAW_KEYS_OPTIONAL = (
    "localidade_ibge", "ponto_cotacao_id", "qualidade_id",
    "condicao_entrega_id", "condicao_pagamento_id",
    "regime_tributario_id", "revisao_de_sha256",
)


def row(d="2026-10-13", price="1000"):
    registro = {
        "mercado": "CME", "produto": "SOJA", "contrato": "2026-11",
        "tipo": "AJUSTE", "unidade": "USC/BU", "instrumento_id": "ZS",
        "data_referencia": d, "competencia": d[:7],
        "referencia_em": d + "T16:00:00-04:00",
        "publicacao_em": d + "T16:30:00-04:00",
        "coleta_em": d + "T17:00:00-04:00",
        "fonte_id": "FONTE-TESTE", "fonte_url": "https://example.org/csv",
        "edicao_sha256": "a" * 64, "preco": price,
    }
    for key in RAW_KEYS_OPTIONAL:
        registro[key] = None
    return registro


def kit(rows=None):
    rows = rows if rows is not None else [row()]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow(COLUNAS)
    for r in rows:
        writer.writerow(["" if r.get(key) is None else r[key] for key in COLUNAS])
    raw = buf.getvalue().encode("utf-8")
    raw_lines = raw.splitlines(keepends=True)
    normalized = []
    for i, data in enumerate(rows, 2):
        normalized.append({**data,
                           "raw_linha": i,
                           "raw_linha_sha256": sha256(raw_lines[i-1]).hexdigest()})
    js = b"".join((json.dumps(r, ensure_ascii=True,
                              sort_keys=True, separators=(",", ":")) + "\n").encode()
                  for r in normalized)
    manifest = {
        "schema": "NIVON_MARKET_RAW_NORM_V1",
        "fonte_id": "FONTE-TESTE",
        "fonte_url": "https://example.org/csv",
        "raw_sha256": sha256(raw).hexdigest(),
        "normalizado_sha256": sha256(js).hexdigest(),
        "capturado_em": "2026-10-15T10:00:00Z",
        "parser_id": CSV_PARSER_ID, "parser_versao": CSV_PARSER_VERSAO,
        "direitos_status": "NAO_HOMOLOGADO",
    }
    return raw, js, manifest


def rehash(raw, js, manifest):
    return {**manifest, "raw_sha256": sha256(raw).hexdigest(),
            "normalizado_sha256": sha256(js).hexdigest()}


def to_jsonl(rows):
    return b"".join((json.dumps(r, ensure_ascii=True, sort_keys=True,
                                  separators=(",", ":")) + "\n").encode()
                    for r in rows)


def verificar(raw, js, manifest):
    return verificar_extracao_csv_canonico(
        raw, js, manifesto=manifest, as_of=CORTE
    )


class TestExtracaoCSVMercados(unittest.TestCase):
    def test_duas_linhas_com_hash_e_correspondencia_1para1(self):
        raw, js, m = kit([row(), row("2026-10-14", "1005.125")])
        r = verificar(raw, js, m)
        self.assertEqual(r["periodos"], 2)
        self.assertEqual(r["serie"][1]["valor_decimal"], "1005.125")
        prova = r["evidencia_extracao_csv"]
        self.assertEqual(prova["registros_conferidos"], 2)
        self.assertEqual(len(prova["linhas_sha256"]), 2)
        self.assertTrue(prova["totalidade_linhas_csv_verificada"])
        self.assertFalse(prova["parser_oficial_mercado_validado"])
        self.assertFalse(r["publicavel"])

    def test_preco_mudou_mesmo_com_dois_hashes_novos(self):
        raw, js, m = kit()
        x = json.loads(js)
        x["preco"] = "1300"
        js2 = to_jsonl([x])
        with self.assertRaisesRegex(ErroExtracaoCSV, "divergência"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_omissao_linha_mesmo_com_hashes_validos(self):
        raw, js, m = kit([row(), row("2026-10-14", "1005")])
        js2 = js.splitlines(keepends=True)[0]
        with self.assertRaisesRegex(ErroExtracaoCSV, "omissão"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_injecao_linha_mesmo_com_hashes_validos(self):
        raw, js, m = kit()
        data = json.loads(js)
        data["raw_linha"] = 3
        js2 = js + to_jsonl([data])
        with self.assertRaisesRegex(ErroExtracaoCSV, "omissão"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_ordem_linhas_nao_intercambiavel(self):
        raw, js, m = kit([row(), row("2026-10-14", "1005")])
        js2 = b"".join(reversed(js.splitlines(keepends=True)))
        with self.assertRaisesRegex(ErroExtracaoCSV, "divergência"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_hash_linha_errado_mas_manifesto_atualizado(self):
        raw, js, m = kit()
        x = json.loads(js)
        x["raw_linha_sha256"] = "f"*64
        js2 = to_jsonl([x])
        with self.assertRaisesRegex(ErroExtracaoCSV, "divergência"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_proveniencia_linha_mentirosa(self):
        raw, js, m = kit()
        x = json.loads(js)
        x["raw_linha"] = 7
        js2 = to_jsonl([x])
        with self.assertRaisesRegex(ErroExtracaoCSV, "divergência"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_extras_no_jsonl_bloqueados(self):
        raw, js, m = kit()
        x = json.loads(js)
        x["payload_injetado"] = "nao executa"
        js2 = to_jsonl([x])
        with self.assertRaisesRegex(ErroExtracaoCSV, "extras"):
            verificar(raw, js2, rehash(raw, js2, m))

    def test_csv_com_cabecalho_ou_coluna_trocada(self):
        raw, js, m = kit()
        raw2 = raw.replace(b"mercado;produto", b"produto;mercado", 1)
        with self.assertRaisesRegex(ErroExtracaoCSV, "cabeçalho"):
            verificar(raw2, js, rehash(raw2, js, m))

    def test_csv_sem_terminador_rejeitado(self):
        raw, js, m = kit()
        raw2 = raw.rstrip(b"\n")
        with self.assertRaisesRegex(ErroExtracaoCSV, "terminador"):
            verificar(raw2, js, rehash(raw2, js, m))

    def test_csv_com_bom_rejeitado(self):
        raw, js, m = kit()
        raw2 = b"\xef\xbb\xbf" + raw
        with self.assertRaisesRegex(ErroExtracaoCSV, "BOM"):
            verificar(raw2, js, rehash(raw2, js, m))

    def test_outro_parser_versao_bloqueado(self):
        raw, js, m = kit()
        m["parser_versao"] = "2"
        with self.assertRaisesRegex(ErroExtracaoCSV, "parser"):
            verificar(raw, js, m)

    def test_fisico_com_condicoes_completas(self):
        físico = row(price="141.25")
        físico.update({
            "mercado": "FISICO", "contrato": None, "instrumento_id": None,
            "localidade_ibge": "5107602", "ponto_cotacao_id": "ARMAZEM-01",
            "qualidade_id": "PADRAO-01", "condicao_entrega_id": "FOB",
            "condicao_pagamento_id": "D7", "regime_tributario_id": "ICMS-ID",
            "tipo": "INDICADOR_FISICO", "unidade": "BRL/SC60KG",
        })
        raw, js, m = kit([físico])
        r = verificar(raw, js, m)
        self.assertEqual(r["identidade_economica"][7], "ARMAZEM-01")
        self.assertFalse(r["publicavel"])


if __name__ == "__main__":
    unittest.main()
