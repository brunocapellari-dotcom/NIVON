import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from nivon.ivo_aprendizado import (
    ErroAprendizado, EvidenciaConhecimento, CandidatoConhecimento,
    PontoPrevisao, avaliar_conhecimento, avaliar_modelo,
)

UTC = timezone.utc
T = datetime(2026, 10, 19, 10, tzinfo=UTC)


def fonte(fid, org, primaria, dias=0, direitos=True):
    return EvidenciaConhecimento(
        fonte_id=fid, organizacao_id=org, sha256_documento=sha256(fid.encode()).hexdigest(),
        publicado_em=T - timedelta(days=3 + dias),
        coletado_em=T - timedelta(days=1), fonte_primaria=primaria,
        direitos_validos=direitos,
    )


def serie(n=8, previsao=102.0, baseline=120.0):
    return tuple(PontoPrevisao(
        periodo=f"2026-{i + 1:02d}",
        emitida_em=datetime(2026 - (i == 0), 12 if i == 0 else i, 28, tzinfo=UTC),
        publicado_observado_em=datetime(2026, i + 2, 3, tzinfo=UTC),
        observado=100., previsto=previsao, baseline=baseline)
        for i in range(n))


class TestConhecimentoIVO(unittest.TestCase):
    def candidato(self, fontes=None, contradicao=False):
        return CandidatoConhecimento(
            afirmacao="Condição climática afeta calendário agrícola",
            dominio="METEOROLOGIA", corte=T,
            evidencias=fontes or (fonte("oficial", "ANA", True), fonte("independente", "INMET", False)),
            contradicao_nao_resolvida=contradicao)

    def test_duas_organizacoes_e_fonte_primaria_so_propem_auditoria(self):
        result = avaliar_conhecimento(self.candidato())
        self.assertEqual(result["estado"], "PRONTO_PARA_AUDITORIA")
        self.assertFalse(result["promovido_canonico"])

    def test_mesma_organizacao_nao_independente(self):
        result = avaliar_conhecimento(self.candidato((fonte("a", "ORG", True), fonte("b", "ORG", False))))
        self.assertEqual(result["estado"], "QUARENTENA")

    def test_fonte_duplicada_bloqueada(self):
        with self.assertRaises(ErroAprendizado):
            avaliar_conhecimento(self.candidato((fonte("a", "ORG", True), fonte("a", "OUTRO", False))))

    def test_contradicao_bloqueada(self):
        self.assertEqual(avaliar_conhecimento(self.candidato(contradicao=True))["estado"], "QUARENTENA")

    def test_direitos_bloqueados(self):
        with self.assertRaises(ErroAprendizado):
            avaliar_conhecimento(self.candidato((fonte("a", "ORG", True, direitos=False),)))

    def test_lookahead_bloqueado(self):
        f = fonte("a", "ORG", True)
        futuro = EvidenciaConhecimento(**{**f.__dict__, "coletado_em": T + timedelta(days=1)})
        with self.assertRaises(ErroAprendizado):
            avaliar_conhecimento(self.candidato((futuro,)))


class TestPrevisaoIVO(unittest.TestCase):
    def test_melhora_mas_nao_promove_producao(self):
        resultado = avaliar_modelo(serie(), modelo_id="SOJA_MT", dados_reais_homologados=True)
        self.assertTrue(resultado["supera_baseline"])
        self.assertEqual(resultado["estado"], "PRONTO_PARA_AUDITORIA")
        self.assertFalse(resultado["promovido_operacional"])

    def test_dados_sinteticos_nao_homologam(self):
        self.assertEqual(avaliar_modelo(serie(), modelo_id="SOJA_MT")["estado"], "NAO_HOMOLOGADO")

    def test_modelo_pior_nao_homologa(self):
        self.assertFalse(avaliar_modelo(serie(previsao=130, baseline=102),
                      modelo_id="SOJA_MT", dados_reais_homologados=True)["supera_baseline"])

    def test_baseline_perfeito_sem_divisao_por_zero(self):
        res = avaliar_modelo(serie(previsao=102, baseline=100), modelo_id="SOJA_MT")
        self.assertIsNone(res["melhoria_relativa_sobre_baseline"])

    def test_fold_duplicado(self):
        pts = serie()
        with self.assertRaises(ErroAprendizado):
            avaliar_modelo(pts[:-1] + (pts[0],), modelo_id="SOJA_MT")

    def test_observacao_futura_na_previsao(self):
        pts = list(serie())
        p = pts[0]
        pts[0] = PontoPrevisao(p.periodo, T, T - timedelta(days=1), p.observado, p.previsto, p.baseline)
        with self.assertRaises(ErroAprendizado):
            avaliar_modelo(tuple(pts), modelo_id="SOJA_MT")

    def test_nao_aceita_previsao_no_mes_alvo(self):
        pts = list(serie())
        p = pts[0]
        pts[0] = PontoPrevisao(p.periodo, datetime(2026, 1, 2, tzinfo=UTC),
                              p.publicado_observado_em, p.observado, p.previsto, p.baseline)
        with self.assertRaises(ErroAprendizado):
            avaliar_modelo(tuple(pts), modelo_id="SOJA_MT")

    def test_periodo_invalido(self):
        pts = list(serie())
        p = pts[0]
        pts[0] = PontoPrevisao("2026-13", p.emitida_em, p.publicado_observado_em,
                              p.observado, p.previsto, p.baseline)
        with self.assertRaises(ErroAprendizado):
            avaliar_modelo(tuple(pts), modelo_id="SOJA_MT")

    def test_amostra_insuficiente(self):
        with self.assertRaises(ErroAprendizado):
            avaliar_modelo(serie(n=3), modelo_id="SOJA_MT")


if __name__ == "__main__":
    unittest.main()
