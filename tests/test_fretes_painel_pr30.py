import unittest
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from nivon.fretes_painel_pr30 import preparar_painel_pr30, ErroPainelFrete
from nivon.fretes_registros import OfertaFrete


def oferta(**kw):
    base = dict(
        publicacao_id="wa:pub1", registro_id="wa:rec1", oferta_id="wa:offer1",
        municipio_ibge="5107925", pickup_entity_id="ponto:001",
        transportadora_id="carrier:001", destino_ibge="5107602",
        descarga_entity_id="terminal:001", produto="SOJA",
        equipamento="RODOTREM", regime="PJ",
        frete_base_brl_t=Decimal("150"), pedagio_brl_t=Decimal("10"),
        frete_cheio_brl_t=Decimal("160"),
        data_referencia=date(2026, 10, 19),
        data_publicacao=datetime(2026, 10, 19, 14, tzinfo=timezone.utc),
        data_coleta=datetime(2026, 10, 19, 15, tzinfo=timezone.utc),
        fonte_id="WHATSAPP_AUTORIZADO",
    )
    base.update(kw)
    return OfertaFrete(**base)


def preparar(rows=None, **kw):
    opts = dict(origem_ibge="5107925", destino_ibge="5107602",
                descarga_entity_id="terminal:001", produto="SOJA",
                equipamento="RODOTREM", regime="PJ", pedagio="ADICIONAL",
                as_of=datetime(2026, 10, 20, 12, tzinfo=timezone.utc))
    opts.update(kw)
    return preparar_painel_pr30(rows if rows is not None else [oferta()], **opts)


class TestPainelPR30(unittest.TestCase):
    def test_prepara_mesma_entidade_com_dados_comparaveis(self):
        p = preparar([oferta(), oferta(
            publicacao_id="wa:pub2", registro_id="wa:rec2",
            oferta_id="wa:offer2", pickup_entity_id="ponto:002",
            transportadora_id="carrier:002", frete_base_brl_t=Decimal("155"),
            frete_cheio_brl_t=Decimal("165"))])
        self.assertEqual(p["motor_destino"], "PR30_TENDENCIA_FRETE_PAREADO")
        self.assertEqual(p["identidades_dia"], 2)
        self.assertFalse(p["publicavel"])
        self.assertIsNone(p["probabilidades_calibradas"])
        self.assertEqual(p["unidade"], "BRL/T_BASE_SEM_PEDAGIO")
        self.assertEqual(p["observacoes"][0]["natureza"], "OFERTA")
        self.assertEqual(p["observacoes"][0]["unidade"], "BRL/T")
        self.assertEqual(p["observacoes"][0]["preco_rs_t"], "150")
        self.assertNotIn("frete_cheio_brl_t", str(p["observacoes"]))
        self.assertNotIn("media_municipal", str(p))
        self.assertEqual(len(p["observacoes"][0]["edicao_sha256"]), 64)
        self.assertEqual(p["edicao_sha256_classe"], "DIGEST_DERIVADO_NAO_PROVA_RAW")

    def test_repostagens_mesmo_valor_nao_viram_pares_independentes(self):
        a = oferta()
        b = replace(a, registro_id="wa:rec2", oferta_id="wa:offer2",
                    publicacao_id="wa:pub2")
        p = preparar([a, b])
        self.assertEqual(p["quantidade_bruta"], 2)
        self.assertEqual(p["identidades_dia"], 1)
        self.assertEqual(p["repeticoes_mesmo_ponto_e_preco"], 1)

    def test_conflitos_mesmo_ponto_transportadora_dia_falham_fechado(self):
        a = oferta()
        b = replace(a, registro_id="wa:rec2", oferta_id="wa:offer2",
                    frete_base_brl_t=Decimal("155"),
                    frete_cheio_brl_t=Decimal("165"))
        with self.assertRaisesRegex(ErroPainelFrete, "conflitantes"):
            preparar([a,b])

    def test_pedagio_desconhecido_nao_e_zero(self):
        a = oferta(pedagio_brl_t=None, frete_cheio_brl_t=None)
        with self.assertRaisesRegex(ErroPainelFrete, "pedágio"):
            preparar([a])
        b = preparar([a], pedagio="NAO_INFORMADO")
        self.assertEqual(b["observacoes"][0]["pedagio"], "NAO_INFORMADO")

    def test_campo_economico_heterogeneo_rejeitado(self):
        a = oferta()
        for kw in [
            {"pickup_entity_id": "ponto:002", "descarga_entity_id": "terminal:002"},
            {"transportadora_id": "carrier:002", "regime": "PF"},
            {"produto": "MILHO"}, {"equipamento": "BITREM"},
            {"destino_ibge": "4106902"},
        ]:
            with self.subTest(kw=kw), self.assertRaisesRegex(ErroPainelFrete, "mistura"):
                b = replace(a, registro_id="wa:rec2", oferta_id="wa:offer2", **kw)
                preparar([a,b])

    def test_duas_transportadoras_mesmo_local_sao_pares_distintos(self):
        a = oferta()
        b = replace(a, registro_id="wa:rec2", oferta_id="wa:offer2",
                    transportadora_id="carrier:002", frete_base_brl_t=Decimal("155"),
                    frete_cheio_brl_t=Decimal("165"))
        p = preparar([a,b])
        self.assertEqual({x["transportadora_id"] for x in p["observacoes"]},
                         {"carrier:001","carrier:002"})

    def test_data_intradiaria_asof_bloqueia_lookahead(self):
        with self.assertRaisesRegex(ErroPainelFrete, "futura"):
            preparar([oferta()], as_of=datetime(
                2026, 10, 19, 14, 30, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ErroPainelFrete, "futura"):
            preparar([oferta()], as_of=datetime(
                2026, 10, 19, 13, tzinfo=timezone.utc))
        with self.assertRaisesRegex(ErroPainelFrete, "timezone"):
            preparar([oferta()], as_of=datetime(2026, 10, 20, 12))

    def test_id_registro_duplicado_mesmo_sem_preco_rejeitado(self):
        with self.assertRaisesRegex(ErroPainelFrete, "registro_id duplicado"):
            preparar([oferta(), oferta()])

    def test_hash_derivado_registra_todas_as_republicacoes(self):
        primeira=oferta()
        segunda=replace(primeira, registro_id="wa:rec2",
                       publicacao_id="wa:pub2", oferta_id="wa:offer2")
        hash_original=preparar([primeira])["observacoes"][0]["edicao_sha256"]
        hash_repetido=preparar([primeira,segunda])["observacoes"][0]["edicao_sha256"]
        self.assertNotEqual(hash_original,hash_repetido)
        self.assertEqual(preparar([primeira,segunda])["identidades_dia"],1)

    def test_anuncio_antigo_republicado_hoje_nao_gera_serie_historica(self):
        velho=oferta(data_referencia=date(2024,1,1))
        with self.assertRaisesRegex(ErroPainelFrete,"referência defasada"):
            preparar([velho])

    def test_decimal_com_precisao_perdida_nao_entra_no_motor(self):
        preco=Decimal("123.12345678912345678")
        anuncio=oferta(frete_base_brl_t=preco,
                       frete_cheio_brl_t=preco+Decimal("10"))
        with self.assertRaisesRegex(ErroPainelFrete,"precisão monetária"):
            preparar([anuncio])

    def test_mudar_pedagio_mantendo_base_bloqueia_em_vez_de_ocultar_reajuste(self):
        primeira=oferta()
        segundo=replace(primeira, registro_id="wa:rec2", oferta_id="wa:offer2",
                       publicacao_id="wa:pub2", pedagio_brl_t=Decimal("25"),
                       frete_cheio_brl_t=Decimal("175"))
        with self.assertRaisesRegex(ErroPainelFrete,"pedágios conflitantes"):
            preparar([primeira,segundo])

    def test_unidade_proibida_e_ausencia_prova_nao_autorizam_publicacao(self):
        p = preparar([oferta()])
        self.assertFalse(p["publicavel"])
        self.assertEqual(p["origem_e_direitos_auditoria_externa"], "PENDENTE_HOMOLOGACAO")
        with self.assertRaises(ErroPainelFrete):
            preparar([oferta()], pedagio="INCLUSO")


if __name__ == "__main__":
    unittest.main()
