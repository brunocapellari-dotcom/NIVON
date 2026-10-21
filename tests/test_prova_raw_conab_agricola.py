"""Prova de RAW: testes sintéticos, NÃO snapshots oficiais."""
from __future__ import annotations

from hashlib import sha256
import unittest

from nivon.prova_raw_conab_agricola import ErroProvaRawConab, verificar_raw_conab
from nivon.auditoria_conab_pam import preparar_tripla_conab, confrontar_conab_pam
from test_auditoria_conab_pam import conab_rows, pam, periodo, cobertura, meta


CAPTURE = "2026-10-21T09:00:00-03:00"
URL_SOJA = "https://www.gov.br/conab/arquivos/SojaSerieHist.xls"
URL_MILHO = "https://www.gov.br/conab/arquivos/MilhoTotalSerieHist.xls"
HEAD = bytes.fromhex("d0cf11e0a1b11ae1")
FAKE_XLS = HEAD + b"\0" * 504


def html_document(*, origem=URL_SOJA, cultura="SOJA"):
    links = {origem: "SojaSerieHist.xls"} if cultura == "SOJA" else {
        URL_MILHO: "MilhoTotalSerieHist.xls",
        "https://www.gov.br/conab/arquivos/Milho1aSerieHist.xls": "Milho1aSerieHist.xls",
        "https://www.gov.br/conab/arquivos/Milho2aSerieHist.xls": "Milho2aSerieHist.xls",
        "https://www.gov.br/conab/arquivos/Milho3aSerieHist.xls": "Milho3aSerieHist.xls",
    }
    return ("<html><body>" + "".join(
        f'<a href="{url}">{label}</a>' for url, label in links.items()
    ) + "</body></html>").encode()


def kwargs(*, cultura="SOJA", filename="SojaSerieHist.xls", url=URL_SOJA):
    payload = FAKE_XLS
    return dict(
        cultura=cultura, arquivo=filename,
        pagina_html_raw=html_document(cultura=cultura),
        planilha_raw=payload, url_documento=url,
        coletado_html_em=CAPTURE, coletado_xls_em=CAPTURE,
        sha256_xls_esperado=sha256(payload).hexdigest())


class TestProvaRawConabAgricola(unittest.TestCase):
    def test_manifesto_de_bytes_sem_edicao_comprovada(self):
        data = verificar_raw_conab(**kwargs())
        self.assertEqual(data["cultura"], "SOJA")
        self.assertEqual(data["xls_raw_sha256"], sha256(FAKE_XLS).hexdigest())
        self.assertEqual(data["html_raw_sha256"],
                         sha256(kwargs()["pagina_html_raw"]).hexdigest())
        self.assertEqual(data["snapshot_meta"]["edicao_id"], "DESCONHECIDA")
        self.assertIsNone(data["snapshot_meta"]["publicado_em"])
        self.assertIsNone(data["snapshot_meta"]["disponivel_em"])
        self.assertFalse(data["vintage_asof_comprovada"])
        self.assertFalse(data["habilita_backtest"])
        self.assertFalse(data["habilita_publicacao"])

    def test_milho_total_e_safras_distintas(self):
        data = verificar_raw_conab(**kwargs(
            cultura="MILHO", filename="MilhoTotalSerieHist.xls", url=URL_MILHO))
        self.assertEqual(data["subdivisao_safra"], "TOTAL")
        self.assertFalse(data["habilita_treino"])
        self.assertEqual(data["snapshot_meta"]["fonte_id"], "CONAB")

    def test_hash_diferente_nao_eh_prova(self):
        inputs = kwargs()
        inputs["sha256_xls_esperado"] = "a" * 64
        with self.assertRaisesRegex(ErroProvaRawConab, "SHA"):
            verificar_raw_conab(**inputs)

    def test_arquivo_truncado_ou_sem_formato_ole2_bloqueado(self):
        for raw in (b"", HEAD, b"PK" + b"\0"*510):
            inputs = kwargs()
            inputs["planilha_raw"] = raw
            inputs["sha256_xls_esperado"] = sha256(raw).hexdigest()
            with self.assertRaises(ErroProvaRawConab):
                verificar_raw_conab(**inputs)

    def test_paginas_com_link_adulterado_ou_outro_host(self):
        for html in (
            html_document(origem="https://evil.example/SojaSerieHist.xls"),
            html_document(origem="http://www.gov.br/conab/SojaSerieHist.xls"),
            b"<html>sem links</html>",
        ):
            inputs = kwargs()
            inputs["pagina_html_raw"] = html
            with self.assertRaises(ErroProvaRawConab):
                verificar_raw_conab(**inputs)

    def test_url_do_xls_deve_corresponder_a_pagina_capturada(self):
        inputs = kwargs()
        inputs["url_documento"] = "https://www.gov.br/conab/arquivos/outra.xls"
        with self.assertRaisesRegex(ErroProvaRawConab, "URL"):
            verificar_raw_conab(**inputs)

    def test_divergencia_de_minutos_nao_pode_vincular_index_e_xls(self):
        inputs = kwargs()
        inputs["coletado_xls_em"] = "2026-10-21T09:11:00-03:00"
        with self.assertRaisesRegex(ErroProvaRawConab, "10 minutos"):
            verificar_raw_conab(**inputs)

    def test_fusos_distintos_equivalentes(self):
        inputs = kwargs()
        inputs["coletado_html_em"] = "2026-10-21T12:00:00Z"
        data = verificar_raw_conab(**inputs)
        self.assertEqual(data["coletado_html_em"], data["coletado_xls_em"])

    def test_contrato_com_metadado_sem_publicacao_reprova_pit(self):
        data = verificar_raw_conab(**kwargs())
        m = data["snapshot_meta"]
        rows = [dict(row, origem_sha256=m["raw_sha256"],
                     coletado_em=CAPTURE) for row in conab_rows()]
        stage = preparar_tripla_conab(linhas=rows, uf="MT",
                 cultura="SOJA", subdivisao="TOTAL",
                 safra="2024/2025", snapshot_meta=m,
                 emitido_em="2026-10-21T10:00:00-03:00")
        self.assertIsNone(stage["data_publicacao"])
        self.assertEqual(stage["estado"], "TRIPLA_CONAB_SEM_PROVA_ASOF")
        pam_agg = pam()
        result = confrontar_conab_pam(
            pacote_conab=stage, agregado_pam=pam_agg,
            meta_pam=meta(origem="IBGE", digest=pam_agg["raw_sha256"]),
            ano_civil_pam=2025, conversao_temporal=periodo(),
            cobertura_pam=cobertura(),
            emitido_em="2026-10-21T10:00:00-03:00")
        self.assertIsNone(result["diferenca_producao_t"])
        self.assertIn("CONAB_SEM_PROVA_ASOF", result["motivos"])

    def test_publicacao_sem_disponibilidade_nao_admitida(self):
        from nivon.auditoria_conab_pam import ErroConciliacaoSafra
        m = meta(publicado_em=None)
        with self.assertRaisesRegex(ErroConciliacaoSafra, "ambas"):
            preparar_tripla_conab(linhas=conab_rows(), cultura="SOJA",
                subdivisao="TOTAL", uf="MT", safra="2024/2025",
                snapshot_meta=m, emitido_em="2026-10-21T10:00:00-03:00")

    def test_nao_provar_vintage_sem_datas_ou_flag(self):
        from nivon.auditoria_conab_pam import ErroConciliacaoSafra
        m = meta(publicado_em=None, disponivel_em=None)
        m["disponibilidade_verificada"] = True
        with self.assertRaises(ErroConciliacaoSafra):
            preparar_tripla_conab(linhas=conab_rows(), cultura="SOJA",
                subdivisao="TOTAL", uf="MT", safra="2024/2025",
                snapshot_meta=m, emitido_em="2026-10-21T10:00:00-03:00")

    def test_html_e_xls_tamanhos_e_cultura(self):
        inputs = kwargs()
        inputs["cultura"] = "ALGODAO"
        with self.assertRaises(ErroProvaRawConab):
            verificar_raw_conab(**inputs)
        inputs = kwargs()
        inputs["arquivo"] = "MilhoTotalSerieHist.xls"
        with self.assertRaises(ErroProvaRawConab):
            verificar_raw_conab(**inputs)
        inputs = kwargs()
        inputs["pagina_html_raw"] = b""
        with self.assertRaises(ErroProvaRawConab):
            verificar_raw_conab(**inputs)


if __name__ == "__main__":
    unittest.main()
