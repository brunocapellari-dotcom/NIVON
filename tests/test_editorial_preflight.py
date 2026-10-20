"""Regressões sintéticas do gate editorial: nenhuma rede, cron ou WhatsApp."""
import copy
import hashlib
import unittest

from nivon.editorial_preflight import avaliar_previa_editorial

AGORA = "2026-10-20T15:00:00-03:00"
HASH = "a" * 64


def prova(publicado, coletado):
    return {
        "fonte_id": "FONTE_TESTE", "direitos_publicacao": True,
        "evidencia_direitos_id": "LICENCA_SYNTHETICA_001",
        "sha256_origem": HASH, "publicado_em": publicado,
        "coletado_em": coletado,
    }


def dados():
    texto = (
        "*RESUMO ESTRATÉGICO DO AGRONEGÓCIO — NIVON*\n"
        "Chicago Soja: 1050 USc/bu, fechamento anterior 19/10/2026\n"
        "Plantio de soja avança em Mato Grosso — resumo verificado\n"
        "Sorriso/MT → Dom Aquino/MT: R$ 130/t, 800 t/dia "
        "(volume REFERENCIA, não realizado), ref. 20/10/2026\n"
    )
    edicao = {"estado": "EDICAO_OFFLINE_PREPARADA_SEM_ENVIO",
              "gerado_em": AGORA, "texto": texto,
              "sha256": hashlib.sha256(texto.encode()).hexdigest(),
              "enviado": False}
    noticia = {**prova("2026-10-20T12:00:00-03:00",
                       "2026-10-20T12:10:00-03:00"),
               "titulo": "Plantio de soja avança em Mato Grosso",
               "url": "https://example.org/plantio?utm_source=a",
               "evento_id": "PLANTIO_MT_20261020",
               "publicacao_original_verificada": True}
    cotacao = {**prova("2026-10-19T17:30:00-03:00",
                       "2026-10-20T09:00:00-03:00"),
               "grupo": "CHICAGO", "titulo": "Chicago Soja",
               "valor": "1050", "unidade": "USc/bu",
               "competencia": "2026-10-19", "natureza": "OBSERVADO",
               "referencia_em": "2026-10-19T17:00:00-03:00",
               "sessao_fechamento": "2026-10-19",
               "ultima_sessao_concluida": "2026-10-19",
               "fechamento_confirmado": True}
    frete = {**prova("2026-10-20T11:00:00-03:00",
                     "2026-10-20T11:05:00-03:00"),
             "origem": "Sorriso", "uf_origem": "MT",
             "destino": "Dom Aquino", "uf_destino": "MT",
             "tipo": "FRETE_ANUNCIADO", "valor_rs_t": "130",
             "pickup_entity_id": "ARMAZEM_SINTETICO_10",
             "transportadora": "TRANSP_SINTETICA",
             "produto": "SOJA", "equipamento": "BITREM",
             "regime_pf_pj": "PJ", "condicao_pedagio": "INCLUSO",
             "referencia_em": "2026-10-20T11:00:00-03:00",
             "volume_t_dia": 800, "classificacao_volume": "REFERENCIA",
             "volume_realizado": False}
    return {"edicao": edicao, "gerado_em": AGORA,
            "noticias": [noticia], "cotacoes": [cotacao], "fretes": [frete]}


def avaliar(d):
    return avaliar_previa_editorial(**d)


class TestPreflightEditorial(unittest.TestCase):
    def test_previa_sintetica_consistente_apta_para_revisao_nao_envio(self):
        r = avaliar(dados())
        self.assertTrue(r["apto_revisao"], r["bloqueios"])
        self.assertEqual(r["modo"], "OFFLINE_SEM_ENVIO")
        self.assertIn("CORREDOR_SEM_DADO_VALIDO:SORRISO/MT/RONDONOPOLIS/MT", r["lacunas"])

    def test_nao_aceita_titulo_antigo(self):
        d = dados()
        d["edicao"]["texto"] = d["edicao"]["texto"].replace(
            "RESUMO ESTRATÉGICO", "BRIEFING ESTRATÉGICO")
        d["edicao"]["sha256"] = hashlib.sha256(d["edicao"]["texto"].encode()).hexdigest()
        self.assertIn("TITULO_EDITORIAL_INCORRETO", avaliar(d)["bloqueios"])

    def test_hash_de_texto_modificado_reprovado(self):
        d = dados()
        d["edicao"]["texto"] += "\nMudança sem nova assinatura"
        self.assertIn("SHA_TEXTO_DIVERGENTE", avaliar(d)["bloqueios"])

    def test_nao_aceita_secoes_proibidas(self):
        for heading in ("▶️ Possível impacto Brasil (análise NIVON): alta",
                        "*RESUMO EXECUTIVO*", "MONITORAR: preço da soja"):
            with self.subTest(heading=heading):
                d = dados()
                d["edicao"]["texto"] += "\n" + heading
                d["edicao"]["sha256"] = hashlib.sha256(
                    d["edicao"]["texto"].encode()).hexdigest()
                self.assertIn("SECAO_EDITORIAL_PROIBIDA", avaliar(d)["bloqueios"])

    def test_fronteira_exata_24h(self):
        d = dados()
        d["noticias"][0]["publicado_em"] = "2026-10-19T15:00:00-03:00"
        self.assertTrue(avaliar(d)["apto_revisao"])
        d["noticias"][0]["publicado_em"] = "2026-10-19T14:59:59-03:00"
        self.assertTrue(any("24 horas" in b for b in avaliar(d)["bloqueios"]))

    def test_sem_hora_fuso_ou_coleta_posterior_reprova(self):
        for p, c in [
            ("2026-10-20", "2026-10-20T12:10:00-03:00"),
            ("2026-10-20T12:00:00", "2026-10-20T12:10:00-03:00"),
            ("2026-10-20T12:00:00-03:00", "2026-10-21T12:00:00-03:00"),
        ]:
            with self.subTest(p=p, c=c):
                d = dados()
                d["noticias"][0]["publicado_em"] = p
                d["noticias"][0]["coletado_em"] = c
                self.assertFalse(avaliar(d)["apto_revisao"])

    def test_data_original_e_direitos_externos_obrigatorios(self):
        d = dados()
        d["noticias"][0]["publicacao_original_verificada"] = False
        self.assertFalse(avaliar(d)["apto_revisao"])
        d = dados()
        d["noticias"][0]["direitos_publicacao"] = False
        self.assertFalse(avaliar(d)["apto_revisao"])

    def test_republicacao_mesmo_evento_bloqueada(self):
        d = dados()
        dup = copy.deepcopy(d["noticias"][0])
        dup.update({"titulo": "Agro em MT registra avanço no plantio de soja",
                    "url": "https://example.org/plantio2?utm_campaign=x"})
        d["noticias"].append(dup)
        self.assertTrue(any("duplicada" in b for b in avaliar(d)["bloqueios"]))

    def test_url_canonica_deduplica_parametros_utm(self):
        d = dados()
        dup = copy.deepcopy(d["noticias"][0])
        dup["url"] = "https://example.org/plantio?utm_source=outro"
        dup["evento_id"] = "ID_DIFERENTE"
        dup["titulo"] = "Novo titulo diferenciado para evento"
        d["noticias"].append(dup)
        self.assertTrue(any("duplicada" in b for b in avaliar(d)["bloqueios"]))

    def test_fechamento_mais_recente_sem_sessao_comprovada_bloqueado(self):
        d = dados()
        d["cotacoes"][0]["ultima_sessao_concluida"] = "2026-10-20"
        self.assertTrue(any("fechamento" in b for b in avaliar(d)["bloqueios"]))

    def test_variacao_percentual_inconsistente_bloqueada(self):
        d = dados()
        d["cotacoes"][0]["valor_anterior"] = "1000"
        d["cotacoes"][0]["variacao_pct"] = "20"
        self.assertTrue(any("variação" in b for b in avaliar(d)["bloqueios"]))

    def test_valor_cotacao_diferente_do_publicado_bloqueia(self):
        d = dados()
        d["cotacoes"][0]["valor"] = "1051"
        self.assertTrue(any("não reconciliam com texto" in b
                            for b in avaliar(d)["bloqueios"]))

    def test_referencia_cotacao_diferente_do_texto_bloqueia(self):
        d = dados()
        d["cotacoes"][0]["referencia_em"] = "2026-10-18T17:00:00-03:00"
        d["cotacoes"][0]["sessao_fechamento"] = "2026-10-18"
        d["cotacoes"][0]["ultima_sessao_concluida"] = "2026-10-18"
        self.assertTrue(any("não reconciliam com texto" in b
                            for b in avaliar(d)["bloqueios"]))

    def test_valor_frete_diferente_do_publicado_bloqueia(self):
        d = dados()
        d["fretes"][0]["valor_rs_t"] = "140"
        self.assertTrue(any("valor/data de frete" in b
                            for b in avaliar(d)["bloqueios"]))

    def test_volume_referencia_nao_virar_realizado(self):
        d = dados()
        d["fretes"][0]["volume_realizado"] = True
        self.assertTrue(any("realizado" in b for b in avaliar(d)["bloqueios"]))

    def test_volume_sem_rotulo_editorial_bloqueado(self):
        d = dados()
        d["edicao"]["texto"] = d["edicao"]["texto"].replace(
            "volume REFERENCIA", "produção diária")
        d["edicao"]["sha256"] = hashlib.sha256(d["edicao"]["texto"].encode()).hexdigest()
        self.assertTrue(any("rótulo" in b for b in avaliar(d)["bloqueios"]))

    def test_noticia_auditada_nao_esta_no_texto(self):
        d = dados()
        d["noticias"][0]["titulo"] = "Notícia que não existe na edição atual"
        self.assertTrue(any("notícia auditada ausente" in b
                            for b in avaliar(d)["bloqueios"]))

    def test_nao_aceita_media_municipal_como_frete_individual(self):
        d = dados()
        d["fretes"][0]["tipo"] = "MEDIA_MUNICIPAL"
        self.assertTrue(any("frete não é anúncio" in b for b in avaliar(d)["bloqueios"]))

    def test_sem_revisao_nao_envia_e_nao_aprova(self):
        d = dados()
        d["edicao"]["enviado"] = True
        self.assertIn("ESTADO_EDICAO_INVALIDO", avaliar(d)["bloqueios"])


if __name__ == "__main__":
    unittest.main()
