"""Integração de ingestão RAW HMAC e contratos comerciais: dados sintéticos."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import hmac
import unittest

from nivon.fretes_atestacoes import serializacao_canonica
from nivon.fretes_registros import OfertaFrete, consolidar_ofertas
from nivon.fretes_raw_ponte_quant import (
    DOMINIO, preparar_fretes_quant_com_raw,
)
from nivon.quant_core import ErroQuantitativo

SECRET = b"captura-test-only-" + b"x" * 32
FONTE = "CANAL_TESTE_SEM_DIREITOS_REAIS"
CHAVE = {
    "municipio_ibge": "5107925", "pickup_entity_id": "fazenda:001",
    "transportadora_id": "transp:001", "destino_ibge": "5107602",
    "descarga_entity_id": "terminal:001", "produto": "MILHO",
    "equipamento": "RODOTREM", "regime": "PJ",
}


def fixture():
    a = []
    for i in range(5):
        dia = date(2026, 10, 13) + timedelta(days=i)
        pub = datetime(dia.year, dia.month, dia.day, 16, tzinfo=timezone.utc)
        base = Decimal(150 + i)
        a.append(OfertaFrete(
            publicacao_id=f"wa:pub{i}", registro_id=f"wa:rec{i}",
            oferta_id=f"wa:offer{i}", **CHAVE,
            frete_base_brl_t=base, pedagio_brl_t=Decimal(10),
            frete_cheio_brl_t=base + 10,
            data_referencia=dia, data_publicacao=pub,
            data_coleta=pub + timedelta(hours=1), fonte_id=FONTE,
        ))
    rows = consolidar_ofertas(a)["registros"]
    raws = {}
    recibos = {}
    for row in rows:
        rid = row["registro_id"]
        original = f"RAW ORIGINAL OFFLINE / {rid} / {row['frete_base_brl_t']}".encode()
        raws[rid] = original
        published = datetime.fromisoformat(row["data_publicacao"])
        capture = published + timedelta(minutes=10)
        signed = published + timedelta(minutes=20)
        payload = dict(
            versao=1, emissor_id="INGESTOR_TESTE",
            registro_id=rid, oferta_id=row["oferta_id"],
            publicacao_id=row["publicacoes_origem"][0],
            fonte_id=FONTE, raw_sha256=sha256(original).hexdigest(),
            publicado_em=row["data_publicacao"],
            capturado_em=capture.isoformat(),
            emitido_em=signed.isoformat(),
        )
        payload["assinatura_hmac_sha256"] = hmac.new(
            SECRET, DOMINIO + serializacao_canonica(payload), sha256,
        ).hexdigest()
        recibos[rid] = payload
    return rows, raws, recibos


def executar(rows, raws, recibos, **cfg):
    x = dict(
        chave_captura=SECRET, emissor_esperado="INGESTOR_TESTE",
        chave_economica=CHAVE, fonte_id=FONTE, tipo_valor="CHEIO",
        as_of="2026-10-21T20:00:00Z",
    )
    x.update(cfg)
    return preparar_fretes_quant_com_raw(
        rows, raws=raws, recibos=recibos, **x,
    )


class TestPonteRAW(unittest.TestCase):
    def test_todos_bytes_e_recibos_vinculados_podem_preparar_apenas_offline(self):
        rows, raws, recibos = fixture()
        r = executar(rows, raws, recibos)
        self.assertEqual(r["recibos_raw_conferidos"], 5)
        self.assertEqual(r["registros"], 5)
        self.assertTrue(r["integridade_hmac_coletor_verificada"])
        self.assertEqual(
            {x["edicao_sha256"] for x in r["observacoes_asof"]},
            {sha256(b).hexdigest() for b in raws.values()},
        )
        self.assertFalse(r["autenticidade_origem_independente_comprovada"])
        self.assertFalse(r["armazenamento_worm_comprovado"])
        self.assertFalse(r["direitos_redistribuicao_comprovados"])
        self.assertFalse(r["asof_pronto"])
        self.assertFalse(r["uso_preditivo_real_autorizado"])
        self.assertFalse(r["publicavel"])

    def test_payload_raw_ou_recibo_adulterado_falha(self):
        for modo in ("bytes", "digest", "publicacao_id", "preco_referenciado"):
            rows, raws, recibos = fixture()
            rid = rows[0]["registro_id"]
            if modo == "bytes":
                raws[rid] += b"MALICIOUS"
            elif modo == "digest":
                recibos[rid]["raw_sha256"] = "f" * 64
            elif modo == "publicacao_id":
                recibos[rid]["publicacao_id"] = "wa:fake"
            else:
                rows[0]["fonte_id"] = "FONTE_FALSA"
            with self.subTest(modo=modo), self.assertRaises(ErroQuantitativo):
                executar(rows, raws, recibos)

    def test_assinatura_ausente_errada_ou_emissor_nao_confiavel(self):
        for modo in ("assinatura", "emissor", "segredo"):
            rows, raws, recibos = fixture()
            rid = rows[1]["registro_id"]
            cfg = {}
            if modo == "assinatura":
                recibos[rid]["assinatura_hmac_sha256"] = "a" * 64
            elif modo == "emissor":
                recibos[rid]["emissor_id"] = "OUTRO_COLETOR"
            else:
                cfg["chave_captura"] = b"outra-chave-sintetica-" + b"z" * 32
            with self.subTest(modo=modo), self.assertRaises(ErroQuantitativo):
                executar(rows, raws, recibos, **cfg)

    def test_recibos_incompletos_ou_extras_bloqueiam_lote_inteiro(self):
        for modo in ("falta_raw", "falta_recibo", "extra"):
            rows, raws, recibos = fixture()
            rid = rows[0]["registro_id"]
            if modo == "falta_raw":
                raws.pop(rid)
            elif modo == "falta_recibo":
                recibos.pop(rid)
            else:
                raws["extra"] = b"something"
            with self.subTest(modo=modo), self.assertRaisesRegex(
                ErroQuantitativo, "cobertura"
            ):
                executar(rows, raws, recibos)

    def test_recibo_retroativo_ou_fora_do_corte_rejeitado(self):
        for campo, offset in (
            ("capturado_em", -5),
            ("emitido_em", 120),
        ):
            rows, raws, recibos = fixture()
            rid = rows[0]["registro_id"]
            pub = datetime.fromisoformat(rows[0]["data_publicacao"])
            payload = recibos[rid]
            payload[campo] = (pub + timedelta(minutes=offset)).isoformat()
            sem_sig = {k: v for k, v in payload.items() if k != "assinatura_hmac_sha256"}
            payload["assinatura_hmac_sha256"] = hmac.new(
                SECRET, DOMINIO + serializacao_canonica(sem_sig), sha256
            ).hexdigest()
            with self.subTest(campo=campo), self.assertRaisesRegex(
                ErroQuantitativo, "as-of"
            ):
                executar(rows, raws, recibos)

    def test_republicacoes_multiplas_sem_todos_raws_nao_passam(self):
        rows, raws, recibos = fixture()
        rows[0]["publicacoes_origem"].append("wa:repost")
        with self.assertRaisesRegex(ErroQuantitativo, "republicações"):
            executar(rows, raws, recibos)

    def test_nao_aceita_hash_derivado_do_painel_como_raw(self):
        rows, raws, recibos = fixture()
        rows[0]["edicao_sha256"] = "1" * 64
        with self.assertRaisesRegex(ErroQuantitativo, "pré-existente"):
            executar(rows, raws, recibos)

    def test_sem_condicoes_comerciais_comparaveis_nao_cria_serie(self):
        rows, raws, recibos = fixture()
        rows[0]["regime"] = "PF"
        with self.assertRaises(ErroQuantitativo):
            executar(rows, raws, recibos)

    def test_sem_chave_de_runtime_protegida_ou_emissor_rejeita(self):
        rows, raws, recibos = fixture()
        for cfg in (
            {"chave_captura": b"x"},
            {"emissor_esperado": ""},
        ):
            with self.subTest(cfg=cfg), self.assertRaises(ErroQuantitativo):
                executar(rows, raws, recibos, **cfg)


if __name__ == "__main__":
    unittest.main()
