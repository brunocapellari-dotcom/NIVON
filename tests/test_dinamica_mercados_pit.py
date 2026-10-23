"""Testes historicos point-in-time: fretes, CBOT, composicao e revisoes."""
from __future__ import annotations
import unittest
from nivon.dinamica_mercados_pit import avaliar_dinamica_historica
from nivon.painel_operacional import ErroMotor, montar_painel

AS_OF = "2026-10-23T12:00:00Z"
SERIE = "FRETE_MT_SANTOS_SOJA_T1"


def registros(*, classe="FRETE_ANUNCIADO"):
    values = [100,101,102,103,104,105,106,109,112,115,118,121]
    out = []
    for idx, valor in enumerate(values):
        d = idx + 11
        dia = f"2026-10-{d:02d}"
        campos = {
            "classe": classe, "serie_id": SERIE, "produto": "SOJA",
            "origem": "RONDONOPOLIS", "destino": "SANTOS",
            "transportadora": "OPERADOR_A", "ponto_embarque": "SILO_UM",
            "terminal": "TERMINAL_SANTOS_1", "equipamento": "RODOTREM",
            "regime": "PJ", "pedagio": "ADICIONAL", "tipo_preco": "BASE",
            "banda_absoluta": "1.0",
        }
        if classe == "CBOT":
            campos = {"classe":"CBOT", "serie_id": SERIE, "produto": "SOJA",
                      "contrato": "2027-03", "mercado": "CME",
                      "tipo_preco": "AJUSTE", "banda_absoluta": "1.0"}
        out.append({
            "dataset_id": "BR_FRETE_AVALIACAO" if classe == "FRETE_ANUNCIADO" else "US_CBOT",
            "identidade": f"linha_{idx}", "fingerprint": f"{idx+1:064x}",
            "data_referencia": dia,
            "data_publicacao": dia + "T09:00:00Z",
            "data_coleta": dia + "T10:00:00Z",
            "natureza": "INFORMADO", "valor": str(valor),
            "unidade": "BRL/T" if classe == "FRETE_ANUNCIADO" else "USC/BU",
            "campos": campos,
        })
    return out


def executar(itens, *, classe="FRETE_ANUNCIADO", as_of=AS_OF):
    return avaliar_dinamica_historica(itens, classe=classe, serie_id=SERIE, as_of=as_of)


class DinamicaMercadosPitTests(unittest.TestCase):
    def test_forca_historica_pareada_nao_e_probabilidade(self):
        r = executar(registros())
        self.assertEqual(r["status"], "DINAMICA_DESCRITIVA_OFFLINE_NAO_HOMOLOGADA")
        self.assertEqual(r["dinamica"], "AUMENTO_DE_FORCA")
        self.assertEqual(r["tendencia_atual"], "ALTA")
        self.assertEqual(r["dias_validos"], 12)
        self.assertIsNone(r["probabilidades_calibradas"])
        self.assertFalse(r["publicavel"])

    def test_janelas_permanecem_sem_revisao_futura(self):
        origem = registros()
        alterado = dict(origem[0], valor="9999",
                        data_coleta="2026-10-24T00:00:00Z")
        r1 = executar(origem)
        r2 = executar(origem + [alterado])
        self.assertEqual(r1["tendencia_atual"], r2["tendencia_atual"])
        self.assertEqual(r1["dinamica"], r2["dinamica"])

    def test_valores_diarios_mesma_transportadora_usa_maior_anuncio(self):
        origem = registros()
        extra = dict(origem[-1], identidade="outra_oferta_dia_22",
                     fingerprint="f" * 64, valor="125")
        r = executar(origem + [extra])
        self.assertEqual(r["dias_validos"], 12)
        self.assertEqual(r["agrupamento_diario_frete"],
                         "MAIOR_DIVULGACAO_MESMAS_CONDICOES")

    def test_outra_embarcadora_mesma_cidade_gera_bloqueio(self):
        rows = registros()
        campos = dict(rows[-1]["campos"], ponto_embarque="SILO_DOIS")
        rows[-1] = dict(rows[-1], campos=campos)
        with self.assertRaises(ErroMotor):
            executar(rows)

    def test_banda_metadados_fingerprint_e_frescor_obrigatorios(self):
        for modificacao, esperado in [
            ({"campos": {"banda_absoluta": None}}, "banda_comercial_ausente"),
            ({"fingerprint": None}, "fingerprint_original_ausente"),
            ({"dataset_id": None}, "unidade_ou_fonte_ausente"),
        ]:
            with self.subTest(k=modificacao):
                dados = registros()
                ultimo = dict(dados[-1], **{k:v for k,v in modificacao.items() if k!="campos"})
                if "campos" in modificacao:
                    ultimo["campos"] = dados[-1]["campos"] | modificacao["campos"]
                dados[-1] = ultimo
                self.assertEqual(executar(dados)["motivo"], esperado)
        self.assertEqual(executar(registros()[:6])["motivo"],
                         "historico_menor_que_duas_janelas")
        self.assertEqual(executar(registros(), as_of="2026-11-15T12:00:00Z")["motivo"],
                         "historico_defasado")

    def test_cbot_mesmo_contrato_e_unidade(self):
        dados = registros(classe="CBOT")
        r = executar(dados, classe="CBOT")
        self.assertEqual(r["tendencia_atual"], "ALTA")
        alterado = dict(dados[-1], campos=dados[-1]["campos"] | {"contrato":"2027-05"})
        with self.assertRaises(ErroMotor):
            executar(dados[:-1]+[alterado], classe="CBOT")

    def test_cbot_multiplos_precos_diferentes_mesmo_dia_bloqueado(self):
        dados = registros(classe="CBOT")
        outros = dict(dados[-1], identidade="outro_preco", fingerprint="f"*64,
                      valor="131")
        r = executar(dados + [outros], classe="CBOT")
        self.assertEqual(r["motivo"], "multiplicidade_diaria_ambigua")

    def test_painel_entrega_tendencia_e_dinamica_separadas(self):
        resultado = montar_painel({"series":[{
            "classe": "FRETE_ANUNCIADO", "serie_id": SERIE,
            "observacoes": registros(),
        }]}, as_of=AS_OF)
        q = resultado["quantitativo"][0]
        self.assertEqual(q["tendencia"], "ALTA")
        self.assertEqual(q["dinamica_historica"]["dinamica"], "AUMENTO_DE_FORCA")
        self.assertFalse(q["publicavel"])


if __name__ == "__main__":
    unittest.main()
