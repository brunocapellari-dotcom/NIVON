"""Suíte sintética para seleção temporal e revisões de abate IBGE."""
import unittest
from copy import deepcopy

from nivon.cadeias_adicionais import ObservacaoCadeia
from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_vintages import historico_sidra_asof

PUB1 = "2026-09-21T12:00:00-03:00"
PUB2 = "2026-10-05T12:00:00-03:00"
COL1 = "2026-09-23T12:00:00-03:00"
COL2 = "2026-10-06T12:00:00-03:00"
CUT = "2026-10-07T00:00:00-03:00"
TAB = {"BOVINO": "1092", "SUINO": "1093", "FRANGO": "1094"}


def snap(especie="BOVINO", valor=100, *, pub=PUB1, coleta=COL1,
         hash_char="a", indicador="ABATE_CABECAS", censurado=False,
         competencia="2026-T2", uf="MT"):
    hash_ = hash_char * 64
    data_ref = "1997-03-31" if competencia == "1997-T1" else "2026-06-30"
    obs = ObservacaoCadeia(
        produto=especie, uf=uf, calendario="TRIMESTRE",
        competencia=competencia, indicador=indicador,
        valor=valor, unidade="CABECAS" if indicador == "ABATE_CABECAS" else "KG",
        classificacao="INFORMADO", fonte_id="IBGE", referencia=data_ref,
        publicacao=pub, coleta=coleta, origem_sha256=hash_,
    )
    return {
        "especie": especie, "tabela_sidra": TAB[especie],
        "origem_sha256": hash_, "publicacao": pub, "coleta": coleta,
        "observacoes": [] if censurado else [obs],
        "linhas_indisponiveis": [
            {"uf": uf, "competencia": competencia, "indicador": indicador,
             "situacao": "INDISPONIVEL_OU_SIGILOSO"}
        ] if censurado else [],
        "classificacao": "NORMALIZACAO_OFFLINE_NAO_HOMOLOGADA",
    }


def select(snapshots, *, especie="BOVINO", corte=CUT, **kwargs):
    return historico_sidra_asof(
        snapshots=snapshots, especie=especie, tabela_sidra=TAB[especie],
        corte_asof=corte, **kwargs,
    )


class TestSIDRAVintages(unittest.TestCase):
    def test_revisao_posterior_e_temporal(self):
        antigo = snap(valor=100)
        novo = snap(valor=120, pub=PUB2, coleta=COL2, hash_char="b")
        presente = select([novo, antigo])
        self.assertEqual([o.valor for o in presente["observacoes"]], [120])
        self.assertEqual(len(presente["revisoes"]), 1)
        r = presente["revisoes"][0]
        self.assertEqual((r["valor_anterior"], r["valor_atual"]), (100, 120))
        self.assertEqual(r["sha256_anterior"], "a"*64)
        self.assertEqual(r["sha256_novo"], "b"*64)
        self.assertFalse(presente["amostra_real_homologada"])
        passado = select([novo, antigo], corte="2026-09-24T00:00:00-03:00")
        self.assertEqual([o.valor for o in passado["observacoes"]], [100])
        self.assertEqual(passado["revisoes"], [])

    def test_backfill_hoje_nao_antecipa_conhecimento_historico(self):
        antiga = snap(valor=100, coleta=COL2)
        resultado = select([antiga], corte="2026-09-24T00:00:00-03:00")
        self.assertEqual(resultado["observacoes"], [])
        self.assertEqual(resultado["snapshots_conhecidos_no_corte"], 0)

    def test_publicacao_futura_bloqueada_ate_publicacao(self):
        novo = snap(pub=PUB2, coleta=COL2)
        resultado = select([novo], corte="2026-10-01T00:00:00-03:00")
        self.assertEqual(resultado["observacoes"], [])

    def test_censura_revoga_valor_anterior(self):
        antigo = snap(valor=100)
        novo = snap(pub=PUB2, coleta=COL2, hash_char="b", censurado=True)
        presente = select([antigo, novo])
        self.assertEqual(presente["observacoes"], [])
        self.assertEqual(len(presente["censuras_vigentes"]), 1)
        self.assertEqual(presente["revisoes"][0]["de_status"], "VALOR")
        self.assertEqual(presente["revisoes"][0]["para_status"], "CENSURADO")

    def test_censura_pode_ser_substituida_por_valor(self):
        antigo = snap(censurado=True)
        novo = snap(valor=104, pub=PUB2, coleta=COL2, hash_char="b")
        atual = select([antigo, novo])
        self.assertEqual([o.valor for o in atual["observacoes"]], [104])
        self.assertEqual(atual["revisoes"][0]["valor_anterior"], None)
        self.assertEqual(atual["revisoes"][0]["valor_atual"], 104)

    def test_publicacao_igual_e_valor_alterado_bloqueado(self):
        a = snap(valor=100)
        b = snap(valor=200, pub=PUB1, coleta=COL2, hash_char="b")
        with self.assertRaises(DadoInvalido):
            select([a, b])

    def test_publicacao_igual_e_valor_idêntico_permitido(self):
        a = snap(valor=100)
        b = snap(valor=100, pub=PUB1, coleta=COL2, hash_char="b")
        result = select([a, b])
        self.assertEqual([o.valor for o in result["observacoes"]], [100])
        self.assertEqual(result["revisoes"], [])

    def test_mesmo_snapshot_nao_duplica(self):
        a = snap()
        with self.assertRaises(DadoInvalido):
            select([a, a])

    def test_observacoes_duplicadas_no_snapshot_bloqueadas(self):
        a = snap()
        a["observacoes"].append(a["observacoes"][0])
        with self.assertRaises(DadoInvalido):
            select([a])

    def test_censura_e_valor_simultaneos_bloqueados(self):
        a = snap()
        a["linhas_indisponiveis"] = snap(censurado=True)["linhas_indisponiveis"]
        with self.assertRaises(DadoInvalido):
            select([a])

    def test_snapshot_com_hash_diferente_da_observacao_bloqueado(self):
        a = snap()
        a["origem_sha256"] = "c"*64
        with self.assertRaises(DadoInvalido):
            select([a])

    def test_especies_nao_misturadas(self):
        for especie in ("FRANGO", "SUINO"):
            self.assertEqual([o.valor for o in select([snap(especie=especie)],
                             especie=especie)["observacoes"]], [100])
            with self.assertRaises(DadoInvalido):
                select([snap(especie=especie)], especie="BOVINO")

    def test_sem_evidencia_nao_promove(self):
        r = select([snap()])
        self.assertFalse(r["metadados_publicacao_verificados"])
        self.assertFalse(r["previsao_homologada"])
        self.assertEqual(r["classificacao"],
                         "HISTORICO_OFFLINE_VINTAGES_NAO_HOMOLOGADO")

    def test_periodos_desde_1997(self):
        r = select([snap(competencia="1997-T1")])
        self.assertEqual(r["observacoes"][0].competencia, "1997-T1")

    def test_status_falso_nao_aceito(self):
        a = snap()
        a["classificacao"] = "HOMOLOGADO"
        with self.assertRaises(DadoInvalido):
            select([a])

    def test_limites_sem_truncamento_silencioso(self):
        a = snap()
        for options in ({"max_snapshots": 0}, {"max_observacoes": 0},
                        {"max_observacoes": 1}):
            if options.get("max_observacoes") == 1:
                a2 = snap(hash_char="c", indicador="PESO_CARCACAS_KG")
                dados = [a, a2]
            else:
                dados = [a]
            with self.assertRaises(DadoInvalido):
                select(dados, **options)

    def test_instante_sem_fuso_rejeitado(self):
        with self.assertRaises(DadoInvalido):
            select([snap()], corte="2026-10-07T00:00:00")

    def test_revisoes_diferentes_competencias_sem_conflito(self):
        a = snap(competencia="1997-T1")
        b = snap(competencia="2026-T2", pub=PUB2, coleta=COL2, hash_char="b")
        result = select([a, b])
        self.assertEqual({o.competencia for o in result["observacoes"]},
                         {"1997-T1", "2026-T2"})
        self.assertEqual(result["revisoes"], [])


if __name__ == "__main__":
    unittest.main()
