"""IBGE PAM: known official errata scope without assuming historical values."""
import unittest
from copy import deepcopy
from datetime import date,datetime,timezone

from nivon.ivo_radar_erratas_pam import (
    ErroRadarErrataPAM,carregar_erratas_pam,radar_erratas_pam,
)


def avaliar(catalogo=None,**override):
    kw=dict(catalogo=carregar_erratas_pam() if catalogo is None else catalogo,
            municipio_ibge="5107958",ano=2021,categoria_c81="2713",
            variavel="214",corte=date(2026,10,21))
    kw.update(override)
    return radar_erratas_pam(**kw)


class TestIVORadarErratasPAM(unittest.TestCase):
    def test_tangara_soja_2021_confirmacao_escopo_sem_inventar_valores(self):
        r=avaliar()
        self.assertEqual(r["estado"],"ERRATA_PAM_PUBLICA_IDENTIFICADA_ARQUIVOS_PENDENTES")
        self.assertEqual(len(r["erratas"]),1)
        self.assertEqual(r["erratas"][0]["aviso_em"],"2026-09-17")
        self.assertTrue(r["erratas"][0]["aviso_ja_publicado_no_corte"])
        self.assertFalse(r["evidencia_digital_arquivada"])
        self.assertFalse(r["reconstrucao_valor_anterior_possivel"])
        self.assertFalse(r["treinamento_autorizado"])

    def test_nao_afeta_sorriso_ou_ano_2022_por_contaminacao_geografica(self):
        for change in ({"municipio_ibge":"5107925"},{"ano":2022},
                       {"categoria_c81":"2711"}):
            with self.subTest(change=change):
                self.assertEqual(avaliar(**change)["erratas"],[])

    def test_arandu_sorgo_tres_anos_afetados(self):
        for year in (2020,2022,2023):
            r=avaliar(municipio_ibge="3503109",categoria_c81="2714",ano=year)
            self.assertEqual(len(r["erratas"]),1)
        self.assertFalse(avaliar(municipio_ibge="3503109",
                                categoria_c81="2714",ano=2021)["erratas"])

    def test_aviso_posterior_ao_corte_nao_vira_verdade_asof(self):
        r=avaliar(corte=date(2026,8,31))
        self.assertEqual(len(r["erratas"]),1)
        self.assertFalse(r["erratas"][0]["aviso_ja_publicado_no_corte"])

    def test_indicador_de_area_nao_e_producao_em_toneladas(self):
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(variavel="109")

    def test_corte_sem_timezone_nao_finge_dia(self):
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(corte=datetime(2026,10,21,tzinfo=timezone.utc))

    def test_injecao_de_fonte_nao_oficial_bloqueada(self):
        cfg=deepcopy(carregar_erratas_pam())
        cfg["notices"][0]["source_url"]="https://ibge.gov.br.evil.test/errata"
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(cfg)

    def test_status_de_dados_reais_sem_hash_nunca_habilita_treino(self):
        cfg=deepcopy(carregar_erratas_pam())
        cfg["training_enabled"]=True
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(cfg)

    def test_edicao_com_id_duplicado_rejeitada(self):
        cfg=deepcopy(carregar_erratas_pam())
        cfg["notices"].append(deepcopy(cfg["notices"][0]))
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(cfg)

    def test_numero_anterior_desconhecido_nao_pode_ser_marcado_conhecido(self):
        cfg=deepcopy(carregar_erratas_pam())
        cfg["notices"][0]["original_bytes_known"]=True
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(cfg)

    def test_municipio_nao_homologado_bloqueado(self):
        with self.assertRaises(ErroRadarErrataPAM):
            avaliar(municipio_ibge="510795")

    def test_documenta_cobertura_parcial(self):
        r=avaliar(ano=2018)
        self.assertEqual(r["estado"],"SEM_ERRATA_NO_CATALOGO_LIMITADO")
        self.assertFalse(r["cobertura_catalogo_completa"])


if __name__=="__main__":
    unittest.main()
