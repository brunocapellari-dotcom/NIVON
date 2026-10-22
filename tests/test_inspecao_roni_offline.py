"""RONI: valores históricos de controle consultados na página oficial NOAA.

A amostra 1950-1951 foi TRANSCRITA do arquivo público em 21/10/2026:
https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt
Não representa captura nem SHA-256 dos bytes RAW integrais da origem.
"""
import hashlib
import unittest

from nivon.inspecao_roni_offline import inspecionar_amostra_roni_offline
from nivon.noaa_roni import ENDPOINT_OFICIAL, ErroRONI, SEASONS

# Valores extraídos das 24 primeiras linhas de dados da publicação oficial.
# Preserve a distinção entre transcrição de amostra e arquivo RAW do CPC.
EXCERTO_CPC_1950_1951 = """SEAS   YR  ANOM
DJF  1950 -1.19
JFM  1950 -1.08
FMA  1950 -0.96
MAM  1950 -1.00
AMJ  1950 -0.99
MJJ  1950 -0.75
JJA  1950 -0.38
JAS  1950 -0.32
ASO  1950 -0.29
SON  1950 -0.38
OND  1950 -0.36
NDJ  1950 -0.50
DJF  1951 -0.28
JFM  1951  0.09
FMA  1951  0.48
MAM  1951  0.63
AMJ  1951  0.59
MJJ  1951  0.69
JJA  1951  0.79
JAS  1951  0.97
ASO  1951  1.04
SON  1951  0.98
OND  1951  0.94
NDJ  1951  0.71
"""


def conferir(texto=EXCERTO_CPC_1950_1951, **kwargs):
    raw = texto.encode("ascii")
    opts = {
        "raw": raw, "coletado_em": "2026-10-21T19:00:00Z",
        "endereco_declarado": ENDPOINT_OFICIAL,
        "sha256_recebido": hashlib.sha256(raw).hexdigest(),
    }
    opts.update(kwargs)
    return inspecionar_amostra_roni_offline(**opts)


class TestInspecaoRONIRealTranscrito(unittest.TestCase):
    def test_valores_oficiais_1950_1951_processados_sem_transformar_em_asof(self):
        result = conferir()
        self.assertEqual(result["quantidade_temporadas"], 24)
        self.assertEqual(result["competencia_primeira"], "1950-01")
        self.assertEqual(result["competencia_ultima"], "1951-12")
        self.assertEqual(result["numero_episodios_retrospectivos"], 2)
        self.assertEqual(result["escopo_verificado"], "EXCERTO_24_OU_MAIS")
        self.assertTrue(result["sha256_bruto_conferido"])
        self.assertFalse(result["origem_autenticada_externamente"])
        self.assertFalse(result["observacoes_reais_comprovadas"])
        self.assertFalse(result["publicacao_individual_conhecida"])
        self.assertFalse(result["reconstrucao_historica_asof_aprovada"])
        self.assertFalse(result["aptidao_uso_preditivo"])
        self.assertFalse(result["homologado"])

    def test_excerto_de_24_temporadas_nao_e_arquivo_completo(self):
        with self.assertRaisesRegex(ErroRONI, "somente excerto"):
            conferir(escopo="HISTORICO_DESDE_1950")

    def test_tamanho_da_serie_extensa_e_apenas_gate_de_cobertura(self):
        lines = [
            f"{season} {year} 0.10"
            for year in range(1950, 2025) for season in SEASONS
        ]
        total = len(lines)
        self.assertEqual(total, 900)
        result = conferir(texto="SEAS YR ANOM\n" + "\n".join(lines) + "\n",
                          escopo="HISTORICO_DESDE_1950")
        self.assertEqual(result["quantidade_temporadas"], 900)
        self.assertFalse(result["observacoes_reais_comprovadas"])
        self.assertFalse(result["reconstrucao_historica_asof_aprovada"])
        self.assertFalse(result["homologado"])

    def test_inteiro_arquivo_comecando_1951_nao_e_historico_desde_1950(self):
        lines = [
            f"{season} {year} 0.10"
            for year in range(1951, 2026) for season in SEASONS
        ]
        with self.assertRaisesRegex(ErroRONI, "somente excerto"):
            conferir(texto="SEAS YR ANOM\n" + "\n".join(lines) + "\n",
                     escopo="HISTORICO_DESDE_1950")

    def test_modificacao_de_arquivo_quebra_sha_recebido(self):
        raw = (EXCERTO_CPC_1950_1951 + " ").encode()
        reference_sha = hashlib.sha256(EXCERTO_CPC_1950_1951.encode()).hexdigest()
        with self.assertRaisesRegex(ErroRONI, "SHA-256"):
            conferir(raw=raw, sha256_recebido=reference_sha)

    def test_roni_nao_pode_ser_trocado_por_oni_ou_endpoint_falso(self):
        for value in [
            "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
            "https://evil.example/data/indices/RONI.ascii.txt",
            "http://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt",
        ]:
            with self.subTest(url=value), self.assertRaises(ErroRONI):
                conferir(endereco_declarado=value)

    def test_rejeita_data_de_coleta_sem_fuso(self):
        with self.assertRaises(ErroRONI):
            conferir(coletado_em="2026-10-21T19:00:00")

    def test_rejeita_periodo_faltante_no_excerto(self):
        raw_lines = EXCERTO_CPC_1950_1951.splitlines()
        with self.assertRaises(ErroRONI):
            conferir(texto="\n".join(raw_lines[:5] + raw_lines[6:]) + "\n")

    def test_rejeita_escopo_nao_homologado(self):
        with self.assertRaisesRegex(ErroRONI, "escopo"):
            conferir(escopo="ASOF_COMPROVADO")


if __name__ == "__main__":
    unittest.main()
