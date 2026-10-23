"""Regressão de integração do pipeline completo offline Fretes -> R01/Quant."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import hmac
import unittest

from nivon.fretes_registros import OfertaFrete, ErroRegistroFrete
from nivon.fretes_atestacoes import serializacao_canonica
from nivon.fretes_raw_ponte_quant import DOMINIO
from nivon.pipeline_fretes_quant import executar_lote_fretes_quant
from nivon.quant_core import ErroQuantitativo

KEY = b"synthetic-batch-capture-" + b"t" * 32
ASOF = datetime(2026, 10, 21, 20, tzinfo=timezone.utc)


def anunciados(*, regimes=("PJ",), dias=7):
    rows = []
    for regime in regimes:
        for j in range(dias):
            dia = date(2026, 10, 1) + timedelta(days=j)
            pub = datetime(dia.year, dia.month, dia.day, 16, tzinfo=timezone.utc)
            for i in (1, 2):
                base = Decimal(150 + 10*i + 3*j)
                suffix = f"{regime}:{j}:{i}"
                rows.append(OfertaFrete(
                    publicacao_id="pub:"+suffix,
                    registro_id="reg:"+suffix,
                    oferta_id="oferta:"+suffix,
                    municipio_ibge="5107925",
                    pickup_entity_id=f"ponto:{i}",
                    transportadora_id=f"transportadora:{i}",
                    destino_ibge="5107602", descarga_entity_id="terminal:001",
                    produto="MILHO", equipamento="RODOTREM", regime=regime,
                    frete_base_brl_t=base, pedagio_brl_t=Decimal(10),
                    frete_cheio_brl_t=base+10,
                    data_referencia=dia, data_publicacao=pub,
                    data_coleta=pub+timedelta(hours=1),
                    fonte_id="TESTE_AUTORIZACAO_PENDENTE",
                ))
    return rows


def assinar(rows):
    raws = {}
    recibos = {}
    for r in rows:
        b = ("Raw original sintético " + r.registro_id).encode()
        raws[r.registro_id] = b
        payload = {
            "versao": 1, "emissor_id": "INGESTAO_OFFLINE",
            "registro_id": r.registro_id,
            "oferta_id": r.oferta_id, "publicacao_id": r.publicacao_id,
            "fonte_id": r.fonte_id, "raw_sha256": sha256(b).hexdigest(),
            "publicado_em": r.data_publicacao.isoformat(),
            "capturado_em": (r.data_publicacao+timedelta(minutes=10)).isoformat(),
            "emitido_em": (r.data_publicacao+timedelta(minutes=20)).isoformat(),
        }
        payload["assinatura_hmac_sha256"] = hmac.new(
            KEY, DOMINIO + serializacao_canonica(payload), sha256
        ).hexdigest()
        recibos[r.registro_id] = payload
    return raws, recibos


class TestPipelineOffline(unittest.TestCase):
    def test_lote_sem_raw_gera_r01_e_bloqueia_previsao_por_par(self):
        result = executar_lote_fretes_quant(anunciados(), as_of=ASOF)
        self.assertEqual(result["total_registros_divulgados"], 14)
        self.assertEqual(result["n_series_individuais"], 2)
        self.assertEqual(result["n_paineis_comerciais"], 1)
        self.assertEqual(result["tendencias_pareadas"][0]["resultado"]["tendencia"], "ALTA")
        self.assertTrue(all(
            x["resultado"]["status"]=="BLOQUEADO_SHA_EDICAO_AUSENTE"
            for x in result["series_quantitativas"]
        ))
        self.assertFalse(result["publicavel"])
        self.assertFalse(result["uso_preditivo_real_autorizado"])
        self.assertNotIn("media_municipal", str(result))
        self.assertNotIn("preco_medio", str(result))

    def test_mesmo_municipio_pf_pj_segmentos_separados(self):
        result = executar_lote_fretes_quant(anunciados(regimes=("PJ", "PF")), as_of=ASOF)
        self.assertEqual(result["n_series_individuais"], 4)
        self.assertEqual(result["n_paineis_comerciais"], 2)
        self.assertEqual(
            {x["condicoes"]["regime"] for x in result["tendencias_pareadas"]},
            {"PJ", "PF"}
        )
        self.assertTrue(all(x["resultado"]["tendencia"] == "ALTA"
                            for x in result["tendencias_pareadas"]))
        self.assertFalse(result["publicavel"])

    def test_lote_com_recibo_hmac_completo_continua_offline(self):
        rows = anunciados()
        raws, recibos = assinar(rows)
        result = executar_lote_fretes_quant(
            rows, as_of=ASOF, raws=raws, recibos=recibos,
            chave_captura=KEY, emissor_esperado="INGESTAO_OFFLINE",
        )
        self.assertEqual(result["n_series_individuais"], 2)
        self.assertEqual(result["n_paineis_comerciais"], 1)
        self.assertTrue(result["raw_assinado_verificado_no_lote"])
        for x in result["series_quantitativas"]:
            s = x["resultado"]
            self.assertEqual(s["recibos_raw_conferidos"], 7)
            self.assertTrue(s["integridade_hmac_coletor_verificada"])
            self.assertFalse(s["uso_preditivo_real_autorizado"])
            self.assertFalse(s["publicavel"])

    def test_lote_raw_parcial_bloqueia_tudo(self):
        rows = anunciados()
        raws, recibos = assinar(rows)
        raws.pop(rows[0].registro_id)
        with self.assertRaises(ErroQuantitativo):
            executar_lote_fretes_quant(
                rows, as_of=ASOF, raws=raws, recibos=recibos,
                chave_captura=KEY, emissor_esperado="INGESTAO_OFFLINE",
            )

    def test_lote_sem_asof_ou_chave_invalido(self):
        rows = anunciados()
        with self.assertRaises(ErroRegistroFrete):
            executar_lote_fretes_quant(rows, as_of=datetime(2026, 10, 21, 20))
        with self.assertRaises(ErroRegistroFrete):
            executar_lote_fretes_quant(rows, as_of=ASOF, raws={})

if __name__ == "__main__":
    unittest.main()
