import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from nivon.fretes_registros import (
    OfertaFrete, ErroRegistroFrete, consolidar_ofertas, distancia_e_custo,
)


def oferta(**kwargs):
    x = dict(
        publicacao_id="mensagem-1", registro_id="r-1", oferta_id="oferta:001",
        municipio_ibge="5107925", pickup_entity_id="fazenda:001",
        transportadora_id="transp:001", destino_ibge="5107602",
        descarga_entity_id="terminal:001", produto="MILHO", equipamento="RODOTREM",
        regime="PJ", frete_base_brl_t=Decimal("150.00"),
        pedagio_brl_t=Decimal("10.00"), frete_cheio_brl_t=Decimal("160.00"),
        data_referencia=date(2026, 10, 19),
        data_publicacao=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
        data_coleta=datetime(2026, 10, 19, 13, tzinfo=timezone.utc),
        fonte_id="WHATSAPP_EVENTO_AUTORIZADO",
    )
    x.update(kwargs)
    return OfertaFrete(**x)


class TestFretesRegistros(unittest.TestCase):
    def test_republicacao_com_evidencia_deduplicada(self):
        x = oferta()
        y = replace(x, registro_id="r-2", publicacao_id="mensagem-2")
        z = consolidar_ofertas([x, y])
        self.assertEqual(z["total_publicacoes_recebidas"], 2)
        self.assertEqual(z["total_registros_divulgados"], 2)
        self.assertEqual(z["total_registros_individuais_deduplicados"], 1)
        self.assertEqual(z["republicacoes_confirmadas"], 1)
        self.assertEqual(z["registros"][0]["publicacoes_origem"],
                         ["mensagem-1", "mensagem-2"])
        self.assertNotIn("media_municipal", z)
        self.assertNotIn("preco_medio", str(z))

    def test_mesmo_municipio_estabelecimentos_e_transportadoras_distintos(self):
        a = oferta()
        b = oferta(registro_id="r-3", oferta_id="oferta:002",
                   pickup_entity_id="fazenda:002", transportadora_id="transp:002",
                   frete_base_brl_t=Decimal("200"), frete_cheio_brl_t=Decimal("210"))
        c = oferta(registro_id="r-4", oferta_id="oferta:003",
                   transportadora_id="transp:002", frete_base_brl_t=Decimal("151"),
                   frete_cheio_brl_t=Decimal("161"))
        z = consolidar_ofertas([a,b,c])
        self.assertEqual(z["total_registros_individuais_deduplicados"], 3)
        self.assertEqual(z["pontos_unicos_por_municipio"][0]["quantidade"], 2)
        self.assertEqual(z["pontos_com_multiplas_transportadoras"][0]["pickup_entity_id"],
                         "fazenda:001")
        self.assertEqual(z["transportadoras"], 2)

    def test_alteracao_preco_nao_vira_republicacao(self):
        a = oferta()
        b = oferta(registro_id="r-2", publicacao_id="mensagem-2",
                   frete_base_brl_t=Decimal("155"), frete_cheio_brl_t=Decimal("165"))
        z = consolidar_ofertas([a, b])
        self.assertEqual(z["republicacoes_confirmadas"], 0)
        self.assertEqual(len(z["registros"]), 2)

    def test_id_oferta_de_outro_estabelecimento_bloqueado(self):
        with self.assertRaisesRegex(ErroRegistroFrete, "oferta_id"):
            consolidar_ofertas([oferta(), oferta(registro_id="r-2",
                             pickup_entity_id="fazenda:002")])

    def test_id_registro_conflitante_bloqueado(self):
        with self.assertRaisesRegex(ErroRegistroFrete, "registro_id"):
            consolidar_ofertas([oferta(), oferta(frete_base_brl_t=Decimal("151"),
                             frete_cheio_brl_t=Decimal("161"))])

    def test_valores_e_datas_inconsistentes(self):
        for kw in (
            {"frete_cheio_brl_t": Decimal("159.99")},
            {"frete_base_brl_t": Decimal("NaN")},
            {"pedagio_brl_t": Decimal("-1")},
            {"data_coleta": datetime(2026,10,19,11,tzinfo=timezone.utc)},
            {"data_publicacao": datetime(2026,10,19,12)},
            {"regime": "PF/PJ"},
            {"pickup_entity_id": ""},
            {"municipio_ibge": "SORRISO"},
        ):
            with self.subTest(kw=kw):
                with self.assertRaises(ErroRegistroFrete):
                    oferta(**kw)

    def test_tku_somente_com_distancia_validada(self):
        with self.assertRaises(ErroRegistroFrete):
            distancia_e_custo(frete_cheio_brl_t=Decimal("200"),
                             distancia_km=Decimal("500"), distancia_verificada=False)
        r = distancia_e_custo(frete_cheio_brl_t=Decimal("200"),
                             distancia_km=Decimal("500"), distancia_verificada=True)
        self.assertEqual(r["frete_brl_tku_estimado"], "0.4")
        self.assertNotIn("receita_hipotetica_brl_km_por_veiculo", r)
        r2 = distancia_e_custo(frete_cheio_brl_t=Decimal("200"),
                             distancia_km=Decimal("500"), distancia_verificada=True,
                             carga_efetiva_t=Decimal("40"))
        self.assertEqual(r2["receita_hipotetica_brl_km_por_veiculo"], "16")


if __name__ == "__main__":
    unittest.main()
