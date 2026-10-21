"""Contrato sintetico SIDRA h/y, N1/BR. IDs FICTICIOS: nao oficiais."""
import json
import unittest
from copy import deepcopy
from hashlib import sha256

from nivon.motores import DadoInvalido
from nivon.pecuaria_sidra_abate import normalizar_snapshot_sidra_abate

DIM = {"territorio": "D1C", "periodo": "D2C", "variavel": "D3C",
       "referencia_temporal": "D4C", "inspecao": "D5C"}
CAB = {"NC": "Nivel territorial", "MN": "Unidade de Medida", "V": "Valor",
       "D1C": "Brasil (Codigo)", "D2C": "Trimestre (Codigo)",
       "D3C": "Variavel (Codigo)", "D4C": "Referencia temporal (Codigo)",
       "D5C": "Inspecao (Codigo)"}
# IDs 9999 e 8888 sao inventados para teste: exigem confirmacao em fonte real.
VARS = {"9999": "ABATE_CABECAS", "8888": "PESO_CARCACAS_KG"}
TOTAL = {"referencia_temporal": "0", "inspecao": "0"}
BASE = dict(especie="FRANGO", tabela_sidra="1094", dimensoes=DIM,
            totais=TOTAL, variaveis=VARS,
            publicacao="2026-09-21T12:00:00-03:00",
            coleta="2026-10-20T13:00:00-04:00",
            status_fonte="APROVADA",
            operacoes_autorizadas={"LEITURA", "ARMAZENAMENTO"})


def linha(var, valor, geo="1", nivel="1", periodo="202602"):
    return {"NC": nivel, "MN": "Cabeças" if var == "9999" else "Quilogramas",
            "V": str(valor), "D1C": geo, "D2C": periodo, "D3C": var,
            "D4C": "0", "D5C": "0"}


def json_bytes(*rows, header=None):
    return json.dumps([header or CAB, *rows], ensure_ascii=False).encode("utf-8")


def analisar(raw, **changes):
    return normalizar_snapshot_sidra_abate(raw, **dict(BASE, **changes))


class TestPecuariaSidraSnapshot(unittest.TestCase):
    def test_tres_especies_com_mapa_explicito(self):
        for especie, tabela in (("BOVINO", "1092"), ("SUINO", "1093"),
                                ("FRANGO", "1094")):
            dim = dict(DIM)
            totais = dict(TOTAL)
            head = dict(CAB)
            rows = [linha("9999", 100), linha("8888", 20000)]
            if especie == "BOVINO":
                dim["rebanho"] = "D6C"
                totais["rebanho"] = "0"
                head["D6C"] = "Tipo bovino (Codigo)"
                rows = [dict(x, D6C="0") for x in rows]
            bruto = json_bytes(*rows, header=head)
            resultado = analisar(bruto, especie=especie, tabela_sidra=tabela,
                                dimensoes=dim, totais=totais)
            self.assertEqual(len(resultado["observacoes"]), 2)
            self.assertEqual(resultado["observacoes"][0].referencia, "2026-06-30")
            self.assertEqual(resultado["origem_sha256"], sha256(bruto).hexdigest())
            self.assertFalse(resultado["coleta_real_executada"])
            self.assertFalse(resultado["previsao_homologada"])
            self.assertEqual(resultado["pares_incompletos"], [])

    def test_brasil_e_uf_nao_se_somam(self):
        a = analisar(json_bytes(linha("9999", 1000), linha("8888", 900000),
            linha("9999", 100, "51", "3"), linha("8888", 90000, "51", "3")))
        self.assertEqual({o.uf for o in a["observacoes"]}, {"BR", "MT"})
        self.assertEqual(len(a["observacoes"]), 4)

    def test_missing_nao_vira_zero(self):
        x = analisar(json_bytes(linha("9999", "..."), linha("8888", 30000)))
        self.assertEqual(len(x["observacoes"]), 1)
        self.assertEqual(x["linhas_indisponiveis"][0]["situacao"],
                         "INDISPONIVEL_OU_SIGILOSO")
        self.assertEqual(len(x["pares_incompletos"]), 1)

    def test_zeros_reais_nao_sao_missing(self):
        x = analisar(json_bytes(linha("9999", "0"), linha("8888", "0")))
        self.assertEqual(len(x["observacoes"]), 2)
        self.assertEqual([o.valor for o in x["observacoes"]], [0.0, 0.0])

    def test_nao_duplica_categoria_inspecao(self):
        data = json_bytes(linha("9999", 100), linha("8888", 30000),
                          dict(linha("9999", 20), D5C="1"))
        with self.assertRaises(DadoInvalido):
            analisar(data)

    def test_nao_duplica_meses_e_trimestre(self):
        data = json_bytes(linha("9999", 100), linha("8888", 30000),
                          dict(linha("9999", 30), D4C="1"))
        with self.assertRaises(DadoInvalido):
            analisar(data)

    def test_percentual_ou_variavel_nao_mapeada_rejeitados(self):
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("7", 10)))

    def test_unidade_carcaca_incorreta_rejeitada(self):
        x = dict(linha("8888", 1200), MN="Toneladas")
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(x))

    def test_duplicata_por_mes_uf_indicador_rejeitada(self):
        x = linha("9999", 10)
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(x, x))

    def test_coluna_dimensionada_nao_declarada_rejeitada(self):
        cab = dict(CAB, D7C="Detalhe nao mapeado")
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("9999", 5), header=cab))

    def test_fonte_sem_autorizacao_nega(self):
        for kwargs in ({"status_fonte":"PENDENTE"},
                       {"operacoes_autorizadas":{"LEITURA"}}):
            with self.assertRaises(PermissionError):
                analisar(json_bytes(linha("9999", 5)), **kwargs)

    def test_bruto_muito_grande_limites_invalidos(self):
        for changes in ({"max_bytes": 10}, {"max_linhas": 0}):
            with self.assertRaises(DadoInvalido):
                analisar(json_bytes(linha("9999", 5)), **changes)

    def test_numero_suprimido_malformado_e_cabecas_fracionarias(self):
        for val in ("-1", "NaN", "12,3", "3.5", "999999999999999999999"):
            with self.assertRaises(DadoInvalido):
                analisar(json_bytes(linha("9999", val)))

    def test_data_revisao_anterior_fim_trimestre_bloqueada(self):
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("9999", 1)),
                    publicacao="2026-02-10T00:00:00Z",
                    coleta="2026-10-20T00:00:00Z")

    def test_cabecalho_incompleto_bloqueado(self):
        cab = dict(CAB)
        del cab["MN"]
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("9999", 5), header=cab))

    def test_tabelas_nao_trocaveis(self):
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("9999", 4)), tabela_sidra="1092")

    def test_codigo_periodo_indevido_e_rebanho_extra(self):
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("9999", 4, periodo="202613")))
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(dict(linha("9999", 4), D6C="1")),
                    dimensoes=dict(DIM, rebanho="D6C"))


    def test_inicio_historico_1997_e_1999(self):
        for periodo, fim in (("199701", "1997-03-31"), ("199904", "1999-12-31")):
            x = analisar(json_bytes(linha("9999", 10, periodo=periodo),
                                   linha("8888", 2500, periodo=periodo)))
            self.assertEqual(x["observacoes"][0].referencia, fim)

    def test_antes_1997_rejeitado(self):
        with self.assertRaises(DadoInvalido):
            analisar(json_bytes(linha("9999", 10, periodo="199604")))


    def test_trimestre_precisa_ter_terminado_por_completo(self):
        bruto = json_bytes(linha("9999", 10), linha("8888", 2500))
        with self.assertRaisesRegex(DadoInvalido, "publicacao anterior"):
            analisar(bruto, publicacao="2026-06-30T23:59:00+00:00",
                    coleta="2026-07-01T12:00:00+00:00")
        atual = analisar(bruto, publicacao="2026-07-01T00:00:00+00:00",
                        coleta="2026-07-01T12:00:00+00:00")
        self.assertEqual(len(atual["observacoes"]), 2)


    def test_traco_e_zero_absoluto_nao_missing(self):
        result = analisar(json_bytes(linha("9999", "-"), linha("8888", "0")))
        self.assertEqual(len(result["observacoes"]), 2)
        self.assertEqual([o.valor for o in result["observacoes"]], [0.0, 0.0])
        self.assertEqual(result["linhas_indisponiveis"], [])
        self.assertEqual(result["pares_incompletos"], [])
        self.assertEqual(result["marcadores_sidra"], [{
            "uf": "BR", "competencia": "2026-T2", "indicador": "ABATE_CABECAS",
            "simbolo": "-", "significado": "ZERO_ABSOLUTO",
        }])

    def test_inibido_nao_aplicavel_e_indisponivel_distintos(self):
        for token, rotulo in (("X", "INIBIDO"),
                              ("..", "NAO_APLICAVEL"),
                              ("...", "NAO_DISPONIVEL")):
            result = analisar(json_bytes(linha("9999", token),
                                        linha("8888", "400")))
            self.assertEqual(len(result["observacoes"]), 1)
            self.assertEqual(result["observacoes"][0].valor, 400)
            self.assertEqual(len(result["linhas_indisponiveis"]), 1)
            self.assertEqual(result["marcadores_sidra"][0]["simbolo"], token)
            self.assertEqual(result["marcadores_sidra"][0]["significado"], rotulo)
            self.assertEqual(len(result["pares_incompletos"]), 1)

    def test_sinal_traco_zero_nao_imputa_valor_x(self):
        result = analisar(json_bytes(linha("9999", "-"),
                                    linha("8888", "X")))
        self.assertEqual(len(result["observacoes"]), 1)
        self.assertEqual(result["observacoes"][0].valor, 0)
        self.assertEqual({r["significado"] for r in result["marcadores_sidra"]},
                         {"ZERO_ABSOLUTO", "INIBIDO"})
        self.assertEqual(len(result["linhas_indisponiveis"]), 1)

if __name__ == "__main__":
    unittest.main()
