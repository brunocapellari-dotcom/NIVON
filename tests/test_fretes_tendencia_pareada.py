import unittest
from datetime import date, timedelta

from nivon.motor_tendencias import ErroTendencia
from nivon.tendencias_mercados import (
    tendencia_cbot, tendencia_preco_fisico,
)
from nivon.fretes_tendencia_pareada import tendencia_frete_pareado

SHA = "b" * 64
ORIGEM = "5104526"
DESTINO = "5107602"
PRAÇA = "5104526"


def obs(dia, valor, fonte="TESTE"):
    return {
        "periodo": dia, "publicacao": dia, "coleta": dia, "valor": valor,
        "fonte_id": fonte, "edicao_sha256": SHA,
    }


def datas_sessoes():
    return ["2026-10-07", "2026-10-08", "2026-10-09",
            "2026-10-13", "2026-10-14", "2026-10-15"]


def cbot(valores=None):
    valores = valores or [1050, 1055, 1060, 1065, 1070, 1075]
    return [
        {**obs(d, v), "mercado": "CME", "produto": "SOJA",
         "contrato": "2026-11", "tipo": "AJUSTE", "unidade": "USC/BU"}
        for d, v in zip(datas_sessoes(), valores)
    ]


def fisico(valores=None):
    valores = valores or [100, 101, 102, 103, 104, 105]
    return [
        {**obs(d, v), "produto": "SOJA", "localidade_ibge": PRAÇA,
         "tipo": "INDICADOR_FISICO", "unidade": "BRL/SC60KG"}
        for d, v in zip(datas_sessoes(), valores)
    ]


def fretes(valores=None):
    valores = valores or [150, 153, 156, 159, 162, 165]
    registros = []
    for dia, preco in zip(datas_sessoes(), valores):
        for i in range(3):
            registros.append({
                **obs(dia, preco+i, fonte=f"WA-{i%2}"),
                "origem_ibge": ORIGEM, "destino_ibge": DESTINO,
                "produto": "MILHO", "veiculo": "RODOTREM",
                "pedagio": "ADICIONAL", "natureza": "OFERTA",
                "unidade": "BRL/T", "lote_id": f"FAZENDA-{i}",
                "pickup_entity_id": f"PONTO-{i}",
                "transportadora_id": f"TRANSPORTADORA-{i}",
                "descarga_entity_id": "terminal:001", "regime": "PJ",
                "preco_rs_t": str(preco+i),
            })
    return registros


def analisar_frete(linhas, **extras):
    return tendencia_frete_pareado(
        linhas, origem_ibge=ORIGEM, destino_ibge=DESTINO,
        produto="MILHO", veiculo="RODOTREM", pedagio="ADICIONAL",
        descarga_entity_id="terminal:001", regime="PJ",
        as_of="2026-10-20", janela=6, tolerancia_absoluta=2,
        **extras,
    )


def analisar_cbot(linhas, **extras):
    return tendencia_cbot(
        linhas, produto="SOJA", contrato="2026-11", tipo="AJUSTE",
        fonte_id="TESTE", as_of="2026-10-20", janela=6,
        tolerancia_absoluta=5, **extras,
    )


def analisar_fisico(linhas):
    return tendencia_preco_fisico(
        linhas, produto="SOJA", localidade_ibge=PRAÇA,
        tipo="INDICADOR_FISICO", unidade="BRL/SC60KG",
        fonte_id="TESTE", as_of="2026-10-20", janela=6,
        tolerancia_absoluta=1,
    )


class TestTendenciasPrioritarias(unittest.TestCase):
    def test_cbot_soja_vencimento_unico_alta(self):
        r = analisar_cbot(cbot())
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["segmento"], "CBOT")
        self.assertEqual(r["contrato"], "2026-11")
        self.assertFalse(r["publicavel"])

    def test_cbot_baixa(self):
        self.assertEqual(analisar_cbot(cbot([1075, 1070, 1065, 1060, 1055, 1050]))["tendencia"], "BAIXA")

    def test_cbot_sem_rolagem_arbitraria(self):
        linhas = cbot()
        linhas[3]["contrato"] = "2027-01"
        with self.assertRaisesRegex(ErroTendencia, "misturados"):
            analisar_cbot(linhas)

    def test_cbot_sem_falso_fechamento_de_ajuste(self):
        linhas = cbot()
        linhas[3]["tipo"] = "FECHAMENTO"
        with self.assertRaises(ErroTendencia):
            analisar_cbot(linhas)

    def test_cbot_sem_conversao_unidade_implicita(self):
        linhas = cbot()
        linhas[3]["unidade"] = "USD/T"
        with self.assertRaises(ErroTendencia):
            analisar_cbot(linhas)

    def test_cbot_sem_serie_continua_nao_ajustada(self):
        linhas = cbot()
        linhas[2]["serie_continua"] = True
        with self.assertRaisesRegex(ErroTendencia, "rolagem"):
            analisar_cbot(linhas)

    def test_cbot_fonte_ou_futuro_nao_autorizado(self):
        linhas = cbot()
        linhas[1]["coleta"] = "2026-10-21"
        with self.assertRaises(ErroTendencia):
            analisar_cbot(linhas)

    def test_fisico_por_praca_sem_mistura(self):
        r = analisar_fisico(fisico())
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["localidade_ibge"], PRAÇA)
        self.assertFalse(r["direitos_publicacao_verificados"])

    def test_fisico_nao_mistura_pracas(self):
        linhas = fisico()
        linhas[2]["localidade_ibge"] = "4106902"
        with self.assertRaises(ErroTendencia):
            analisar_fisico(linhas)

    def test_fisico_nao_mistura_indicador_negociado(self):
        linhas = fisico()
        linhas[1]["tipo"] = "NEGOCIADO"
        with self.assertRaises(ErroTendencia):
            analisar_fisico(linhas)

    def test_fisico_estavel(self):
        r = analisar_fisico(fisico([100]*6))
        self.assertEqual(r["tendencia"], "ESTABILIDADE")

    def test_frete_variacao_pareada_sem_pseudovolume(self):
        r = analisar_frete(fretes())
        self.assertEqual(r["tendencia"], "ALTA")
        self.assertEqual(r["segmento"], "FRETE_ANUNCIADO")
        self.assertEqual(r["reenvios_deduplicados"], 0)
        self.assertEqual(r["lotes_distintos_total_por_dia"], 18)
        self.assertEqual(r["cobertura_amostral"][0]["variacao_pareada_mediana_rs_t"], "0")
        self.assertNotIn("volume_transportado", r)

    def test_r01_efeito_composicao_fazendas_estaveis_nao_cria_alta(self):
        # A=100 em todos os dias; B=200 só nos dias 1-3, C=300 nos
        # dias 4-6. Preços individuais NÃO sobem. Medianas brutas 150→200
        # gerariam alta falsa; painel A sozinho é insuficiente.
        lines = []
        for idx, dia in enumerate(datas_sessoes()):
            empresas = (("A", 100), ("B", 200)) if idx < 3 else (("A", 100), ("C", 300))
            for fazenda, preco in empresas:
                lines.append({
                    **obs(dia, preco), "origem_ibge": ORIGEM,
                    "destino_ibge": DESTINO, "produto": "MILHO",
                    "veiculo": "RODOTREM", "pedagio": "ADICIONAL",
                    "natureza": "OFERTA", "unidade": "BRL/T",
                    "lote_id": "LOTE-" + fazenda,
                    "pickup_entity_id": fazenda,
                    "transportadora_id": "TRANSP-" + fazenda,
                    "descarga_entity_id": "terminal:001", "regime": "PJ",
                    "preco_rs_t": str(preco),
                })
        r = analisar_frete(lines)
        self.assertEqual(r["status"], "PAINEL_INCOMPARAVEL")
        self.assertEqual(r["tendencia"], "INDETERMINADA")
        self.assertFalse(r["publicavel"])

    def test_r01_painel_estavel_com_novos_participantes_nao_cria_alta(self):
        # Dois pares comparáveis, ambos estáveis; terceiros mudam
        # de composição e preço entre períodos, mas não afetam o sinal.
        lines = fretes()
        for idx, row in enumerate(lines):
            fazenda = row["lote_id"]
            if fazenda == "FAZENDA-0":
                preco = 100
            elif fazenda == "FAZENDA-1":
                preco = 200
            else:
                preco = 50 if idx // 3 < 3 else 500
                row["pickup_entity_id"] = "PONTO-X" if idx // 3 < 3 else "PONTO-Y"
            row["valor"] = preco
            row["preco_rs_t"] = str(preco)
        r = analisar_frete(lines)
        self.assertEqual(r["tendencia"], "ESTABILIDADE")
        self.assertEqual(len(r["identidades_comparaveis"]), 2)
        self.assertNotIn("preco_mediano_rs_t", str(r))
        self.assertNotIn("media_frete_municipio", str(r))

    def test_r01_limiar_relativo_sem_base_de_preco_nao_e_permitido(self):
        # O sinal usa diferenças em R$/t ancoradas em zero; taxa relativa
        # sobre mediana dessas diferenças produziria limiar indefensável.
        with self.assertRaisesRegex(ErroTendencia, "limiar relativo"):
            analisar_frete(fretes(), tolerancia_relativa=0.05)

    def test_r01_exige_ponto_embarque_e_transportadora(self):
        for campo in ("pickup_entity_id", "transportadora_id"):
            with self.subTest(campo=campo):
                lines = fretes()
                lines[0].pop(campo)
                with self.assertRaises(ErroTendencia):
                    analisar_frete(lines)

    def test_rejeita_descarga_ou_regime_divergentes(self):
        for campo,valor in (("descarga_entity_id","terminal:outro"), ("regime","PF")):
            registros=fretes()
            registros[2][campo]=valor
            with self.subTest(campo=campo), self.assertRaisesRegex(ErroTendencia,"mistura"):
                analisar_frete(registros)

    def test_exige_descarga_e_regime_na_assinatura(self):
        for campo in ("descarga_entity_id","regime"):
            registros=fretes()
            registros[5].pop(campo)
            with self.subTest(campo=campo), self.assertRaisesRegex(ErroTendencia,"mistura"):
                analisar_frete(registros)

    def test_mudanca_apenas_de_composicao_nao_cria_tendencia_falsa(self):
        registros=fretes()
        for day in range(6):
            registros[day*3+2]["pickup_entity_id"]= "ROTATIVO-A" if day<3 else "ROTATIVO-B"
            registros[day*3+2]["valor"]= 100 if day<3 else 600
            registros[day*3+2]["preco_rs_t"]= str(registros[day*3+2]["valor"])
            for i in (0,1):
                registros[day*3+i]["valor"] = 150+i
                registros[day*3+i]["preco_rs_t"]=str(150+i)
        resultado=analisar_frete(registros)
        self.assertEqual(resultado["tendencia"],"ESTABILIDADE")
        self.assertEqual(resultado["metrica_tendencia"],"VARIACAO_PAREADA_POR_ESTABELECIMENTO_TRANSPORTADORA")
        self.assertEqual(len(resultado["identidades_comparaveis"]),2)
        self.assertFalse(resultado["publicavel"])

    def test_frete_20_reposts_nao_viram_lotes(self):
        linhas = fretes()
        base = linhas[0]
        for _ in range(20):
            linhas.append(dict(base))
        r = analisar_frete(linhas)
        self.assertEqual(r["reenvios_deduplicados"], 20)
        self.assertEqual(r["lotes_distintos_total_por_dia"], 18)
        self.assertEqual(r["cobertura_amostral"][0]["variacao_pareada_mediana_rs_t"], "0")

    def test_frete_mesmo_lote_diferente_preco_bloqueia(self):
        linhas = fretes()
        contraria = dict(linhas[0])
        contraria["preco_rs_t"] = "200"
        contraria["valor"] = 200
        linhas.append(contraria)
        with self.assertRaisesRegex(ErroTendencia, "conflitantes"):
            analisar_frete(linhas)

    def test_frete_nao_mistura_destinos(self):
        linhas = fretes()
        linhas[-1]["destino_ibge"] = "1503606"
        with self.assertRaisesRegex(ErroTendencia, "mistura"):
            analisar_frete(linhas)

    def test_frete_nao_mistura_caminhao(self):
        linhas = fretes()
        linhas[4]["veiculo"] = "BITREM"
        with self.assertRaises(ErroTendencia):
            analisar_frete(linhas)

    def test_frete_nao_mistura_pedagio(self):
        linhas = fretes()
        linhas[4]["pedagio"] = "INCLUSO"
        with self.assertRaises(ErroTendencia):
            analisar_frete(linhas)

    def test_frete_nao_mistura_oferta_com_executado(self):
        linhas = fretes()
        linhas[4]["natureza"] = "CONTRATADO"
        with self.assertRaises(ErroTendencia):
            analisar_frete(linhas)

    def test_frete_nao_mistura_unidades(self):
        linhas = fretes()
        linhas[4]["unidade"] = "BRL/VIAGEM"
        with self.assertRaises(ErroTendencia):
            analisar_frete(linhas)

    def test_frete_preco_valor_incoerente(self):
        linhas = fretes()
        linhas[4]["preco_rs_t"] = "123.40"
        with self.assertRaises(ErroTendencia):
            analisar_frete(linhas)

    def test_frete_2_lotes_por_dia_ok_1_bloqueia(self):
        linhas = [r for r in fretes() if r["lote_id"] != "FAZENDA-2"]
        self.assertEqual(analisar_frete(linhas)["tendencia"], "ALTA")
        linhas = [r for r in linhas if r["lote_id"] != "FAZENDA-1"]
        r = analisar_frete(linhas)
        self.assertEqual(r["status"], "AMOSTRA_INSUFICIENTE")
        self.assertEqual(r["tendencia"], "INDETERMINADA")

    def test_frete_dados_insuficientes_quatro_dias(self):
        linhas = fretes()[:12]
        r = analisar_frete(linhas)
        self.assertEqual(r["tendencia"], "INDETERMINADA")
        self.assertEqual(r["status"], "DADOS_INSUFICIENTES")

    def test_frete_sem_lote_resolvido_bloqueia(self):
        linhas = fretes()
        linhas[2].pop("lote_id")
        with self.assertRaises(ErroTendencia):
            analisar_frete(linhas)

    def test_frete_price_zero_nan_bool_fora(self):
        for valor in ["0", "nan", True, "-5"]:
            with self.subTest(valor=str(valor)):
                linhas = fretes()
                linhas[0]["preco_rs_t"] = valor
                with self.assertRaises(ErroTendencia):
                    analisar_frete(linhas)

    def test_frete_cobertura_seis_dias_sem_licenca_de_publicacao(self):
        r = analisar_frete(fretes())
        self.assertEqual(len(r["cobertura_amostral"]), 6)
        self.assertFalse(r["direitos_publicacao_verificados"])
        self.assertFalse(r["publicavel"])


if __name__ == "__main__":
    unittest.main()
