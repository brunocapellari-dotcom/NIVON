"""Auditoria red-team do preflight editorial atualizado; só fixtures sintéticas.

Base factual dos testes: formato canônico da PR #26 em SHA
15bd85044aa5492bd57dac46ff1fd5f615186698. Não publica WhatsApp.
"""
from __future__ import annotations

import hashlib
import unittest

from nivon.editorial_preflight import avaliar_previa_editorial
from nivon.frete_linhas_editoriais import formatar_linha_frete
from test_editorial_preflight import dados


def validar(p):
    return avaliar_previa_editorial(**p)


def texto_atualizar(p, velho, novo):
    texto = p["edicao"]["texto"]
    assert velho in texto
    p["edicao"]["texto"] = texto.replace(velho, novo, 1)
    p["edicao"]["sha256"] = hashlib.sha256(
        p["edicao"]["texto"].encode("utf-8")
    ).hexdigest()


def frete_atualizar(p, **campos):
    frete = p["fretes"][0]
    anterior = formatar_linha_frete({**frete, "referencia": frete["referencia_em"]})
    frete.update(campos)
    depois = formatar_linha_frete({**frete, "referencia": frete["referencia_em"]})
    texto_atualizar(p, anterior, depois)


class TestAuditoriaAtualEditorialIndependente(unittest.TestCase):
    def test_controle_formato_novo_aceito_so_para_revisao_offline(self):
        p = dados()
        r = validar(p)
        self.assertTrue(r["apto_revisao"], r["bloqueios"])
        self.assertEqual(r["modo"], "OFFLINE_SEM_ENVIO")

    def test_nc006_fechamento_antigo_declarado_ultima_sessao_bloqueado(self):
        p = dados()
        p["cotacoes"][0].update({
            "referencia_em": "2026-07-20T17:00:00-03:00",
            "sessao_fechamento": "2026-07-20",
            "ultima_sessao_concluida": "2026-07-20",
            "competencia": "2026-07-20",
        })
        texto_atualizar(p, "19/10/2026", "20/07/2026")
        resultado = validar(p)
        self.assertTrue(
            any(
                b.startswith("COTACAO_0:")
                and any(termo in b.lower() for termo in (
                    "sessão", "sessao", "fechamento", "venc",
                    "atualidade", "janela", "publica", "antig"))
                for b in resultado["bloqueios"]
            ),
            "NC006: rejeição sem prova de validade temporal. "
            f"Bloqueios registrados: {resultado['bloqueios']}",
        )
        self.assertFalse(
            any(not b.startswith("COTACAO_0:") for b in resultado["bloqueios"]),
            f"NC006: outra falha da fixture mascarou a verificação: "
            f"{resultado['bloqueios']}",
        )

    def test_nc007_frete_antigo_republicado_com_linha_correta_bloqueado(self):
        p = dados()
        frete_atualizar(p, referencia_em="2024-10-20T11:00:00-03:00")
        self.assertFalse(validar(p)["apto_revisao"],
                         "NC007: anúncio histórico não é frete corrente")

    def test_nc008_sessao_de_bolsa_local_nao_pode_virar_dia_utc(self):
        p = dados()
        p["cotacoes"][0].update({
            "referencia_em": "2026-10-19T23:30:00-03:00",
            "publicado_em": "2026-10-20T00:30:00-03:00",
        })
        r = validar(p)
        self.assertTrue(r["apto_revisao"],
                        "NC008: referência local da sessão 19/10 não vira 20/10 UTC; "
                        f"bloqueios={r['bloqueios']}")

    def test_nc009_volume_observado_exige_evidencia_de_operacao(self):
        p = dados()
        frete_atualizar(p, classificacao_volume="OBSERVADO", volume_realizado=True)
        self.assertFalse(validar(p)["apto_revisao"],
                         "NC009: volume OBSERVADO não se autocomprova")

    def test_nc010_publicacao_de_fechamento_antes_da_referencia(self):
        p = dados()
        p["cotacoes"][0]["publicado_em"] = "2026-10-19T16:00:00-03:00"
        self.assertFalse(validar(p)["apto_revisao"],
                         "NC010: fonte não publica fechamento antes da hora de referência")

    def test_nc011_publicacao_do_frete_antes_da_referencia(self):
        p = dados()
        p["fretes"][0]["publicado_em"] = "2026-10-20T10:00:00-03:00"
        self.assertFalse(validar(p)["apto_revisao"],
                         "NC011: referência posterior à publicação deve ser rejeitada")


if __name__ == "__main__":
    unittest.main()
