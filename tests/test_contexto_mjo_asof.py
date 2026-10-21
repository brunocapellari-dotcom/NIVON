"""Testes point-in-time da integração MJO/RMM da PR #11."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from nivon.contexto_mjo_asof import (ErroContextoMJO, indexar_contexto_mjo_asof,
                                      contextualizar_nwp_com_mjo_asof)


RMM1 = ("year month day RMM1 RMM2 phase amplitude source\n"
        "2026 10 17 0.60 0.80 6 1.00 Final\n")
RMM2 = (RMM1 + "2026 10 21 0.30 0.40 6 0.50 Final\n")


def snapshot(text=RMM1, published="2026-10-20T13:00:00Z",
             captured="2026-10-20T14:00:00Z"):
    return {
        "texto": text, "fonte_id": "BOM_RMM",
        "publicado_em": published, "coletado_em": captured,
        "raw_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "tipo": "SINTETICO",
        "evidencia_disponibilidade_sha256": hashlib.sha256(
            (captured + text).encode()).hexdigest(),
    }


def issue(tag, at):
    return {"previsao_id": tag, "emitido_em": at}


def run(issues=None, snaps=None, **extra):
    return indexar_contexto_mjo_asof(
        previsoes=issues or [
            issue("NWP1", "2026-10-19T18:00:00Z"),
            issue("NWP2", "2026-10-20T13:30:00Z"),
            issue("NWP3", "2026-10-20T15:00:00Z"),
        ], snapshots_rmm=snaps or [snapshot()], **extra)


def nwp_snapshot(*, issued="2026-10-20T15:00:00Z", captured=None):
    origin = datetime.fromisoformat(issued.replace("Z", "+00:00"))
    published = origin + timedelta(minutes=10)
    capture = captured or (origin + timedelta(minutes=30)).isoformat()
    valid = origin + timedelta(hours=48)
    row = {
        "estacao_id": "INMET_A904", "produto_id": "GEFS_FIXTURE",
        "versao_produto": "synthetic_v1",
        "emitido_em": issued,
        "previsao_publicada_em": published.isoformat(),
        "features_publicadas_ate": (origin - timedelta(hours=1)).isoformat(),
        "climatologia_publicada_em": (origin - timedelta(days=1)).isoformat(),
        "valido_em": valid.isoformat(),
        "membros_mm": [0, 1, 2, 3, 4],
        "prob_climatologica": 0.3,
    }
    raw = json.dumps({"registro": row}, sort_keys=True).encode("utf-8")
    return {
        "manifesto": {
            "dataset_id": "NOAA_GFS", "fonte_id": "NOAA",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "capturado_em": capture, "classe": "SINTETICO",
            "prova_disponibilidade_sha256": hashlib.sha256(b"proof-placeholder").hexdigest(),
        },
        "bytes_json": raw,
    }


class TestContextoMJOAsOf(unittest.TestCase):
    def test_snapshot_tardio_nao_reescreve_passado(self):
        out = run()
        self.assertEqual(out["n_previsoes"], 3)
        self.assertEqual([x["status"] for x in out["contextos"]],
                         ["SEM_VINTAGE_DISPONIVEL", "SEM_VINTAGE_DISPONIVEL",
                          "RMM_OBSERVADO_ATIVO"])
        self.assertIsNone(out["contextos"][0]["fase_fonte"])
        self.assertEqual(out["contextos"][2]["fase_fonte"], 6)
        self.assertAlmostEqual(out["contextos"][2]["amplitude"], 1.0)
        self.assertEqual(out["contextos"][2]["defasagem_dias"], 3)
        self.assertFalse(out["homologado"])
        self.assertFalse(out["uso_modelo_predictivo_permitido"])
        self.assertFalse(out["contextos"][2]["previsao_regional_inferida"])

    def test_revisao_nova_so_vale_depois_de_publicada_capturada(self):
        two = snapshot(RMM2, "2026-10-22T13:00:00Z", "2026-10-22T14:00:00Z")
        res = run(issues=[
            issue("BEFORE", "2026-10-22T13:30:00Z"),
            issue("AFTER", "2026-10-22T15:00:00Z"),
        ], snaps=[two, snapshot()])
        first, second = res["contextos"]
        self.assertEqual(first["status"], "RMM_OBSERVADO_ATIVO")
        self.assertEqual(second["status"], "RMM_OBSERVADO_FRACO")
        self.assertEqual(first["data_indice"], "2026-10-17")
        self.assertEqual(second["data_indice"], "2026-10-21")
        self.assertEqual(second["defasagem_dias"], 1)
        self.assertNotEqual(first["snapshot_sha256"], second["snapshot_sha256"])

    def test_fase_fraca_nao_promove_previsao_municipal(self):
        s = snapshot(RMM2, "2026-10-22T13:00:00Z", "2026-10-22T14:00:00Z")
        out = run(issues=[issue("LATER", "2026-10-22T20:00:00Z")], snaps=[s])
        context = out["contextos"][0]
        self.assertEqual(context["status"], "RMM_OBSERVADO_FRACO")
        self.assertEqual(context["sinal"], "FRACO")
        self.assertFalse(context["previsao_regional_inferida"])
        self.assertFalse(context["modelo_de_chuva_alterado"])

    def test_indice_desatualizado_nao_tem_fase_ou_amplitude_validas(self):
        out = run(
            issues=[issue("STALE", "2026-11-03T20:00:00Z")],
            max_defasagem_dias=4)
        record = out["contextos"][0]
        self.assertEqual(record["status"], "RMM_DESATUALIZADO")
        self.assertIsNone(record["fase_fonte"])
        self.assertIsNone(record["amplitude"])
        self.assertIsNone(record["data_indice"])
        self.assertGreater(record["defasagem_dias"], 4)

    def test_hash_raw_alterado_bloqueado(self):
        s = snapshot()
        s["texto"] += " "
        with self.assertRaisesRegex(ErroContextoMJO, "RAW"):
            run(snaps=[s])

    def test_nao_atesta_fonte_real_sem_catalogo(self):
        s = snapshot()
        s["tipo"] = "REAL_AUTORIZADO"
        with self.assertRaises(PermissionError):
            run(snaps=[s])

    def test_edicao_publicada_antes_do_dia_da_observacao_e_rejeitada(self):
        s = snapshot(RMM2, "2026-10-20T13:00:00Z",
                     "2026-10-22T14:00:00Z")
        with self.assertRaisesRegex(ErroContextoMJO, "anterior à observação"):
            run(snaps=[s])

    def test_edicoes_distintas_mesma_publicacao_e_captura_sao_ambiguas(self):
        s1 = snapshot()
        s2 = snapshot(
            RMM1.replace("0.60 0.80 6 1.00", "0.80 0.60 6 1.00"))
        with self.assertRaisesRegex(ErroContextoMJO, "edições conflitantes"):
            run(snaps=[s1, s2])

    def test_mistura_bom_e_cpc_bloqueada(self):
        s = snapshot()
        s["fonte_id"] = "CPC_MJO"
        with self.assertRaises(ErroContextoMJO):
            run(snaps=[s])

    def test_publicacao_posterior_ou_sem_fuso_bloqueada(self):
        s = snapshot()
        s["publicado_em"] = "2026-10-20T16:00:00Z"
        with self.assertRaisesRegex(ErroContextoMJO, "anterior"):
            run(snaps=[s])
        s = snapshot()
        s["coletado_em"] = "2026-10-20T14:00:00"
        with self.assertRaises(ErroContextoMJO):
            run(snaps=[s])

    def test_dados_rmm_corrompidos_rejeitados_no_parser_original(self):
        s = snapshot(text=RMM1.replace("0.80 6 1.00", "0.80 6 5.00"))
        with self.assertRaisesRegex(ErroContextoMJO, "parser canônico"):
            run(snaps=[s])

    def test_falha_sem_observacao_elegivel_nunca_inventa(self):
        s = snapshot(text="2026 10 18 999 999 999 999 Final\n")
        with self.assertRaises(ErroContextoMJO):
            run(snaps=[s])

    def test_ids_de_emissao_duplicados_bloqueados(self):
        with self.assertRaisesRegex(ErroContextoMJO, "duplicado"):
            run(issues=[issue("DUP", "2026-10-20T16:00:00Z"),
                        issue("DUP", "2026-10-21T16:00:00Z")])

    def test_duplicata_da_mesma_captura_bloqueada(self):
        s = snapshot()
        with self.assertRaisesRegex(ErroContextoMJO, "duplicados"):
            run(snaps=[s, copy.deepcopy(s)])

    def test_registro_de_emissao_sem_timezone_bloqueado(self):
        with self.assertRaisesRegex(ErroContextoMJO, "fuso"):
            run(issues=[issue("NWP1", "2026-10-20T16:00:00")])

    def test_sidecar_hash_nwp_consulta_rmm_na_emissao_nao_na_captura(self):
        before = nwp_snapshot(
            issued="2026-10-20T13:30:00Z",
            captured="2026-10-20T14:30:00Z",
        )
        after = nwp_snapshot(issued="2026-10-20T15:00:00Z")
        out = contextualizar_nwp_com_mjo_asof(
            snapshots_previsao=[before, after],
            snapshots_rmm=[snapshot()], acumulacao_horas=24)
        first, second = out["contextos"]
        self.assertEqual(first["status"], "SEM_VINTAGE_DISPONIVEL")
        self.assertEqual(second["status"], "RMM_OBSERVADO_ATIVO")
        self.assertEqual(first["previsao_id"], before["manifesto"]["sha256"])
        self.assertEqual(second["previsao_id"], after["manifesto"]["sha256"])
        self.assertEqual(out["nwp_hashes_raw_conferidos"], 2)
        self.assertFalse(out["estatisticas_nwp_alteradas"])
        self.assertFalse(out["homologado"])

    def test_nwp_raw_hash_invalido_bloqueia_contexto(self):
        p = nwp_snapshot()
        p["bytes_json"] += b" "
        with self.assertRaisesRegex(ErroContextoMJO, "inválido"):
            contextualizar_nwp_com_mjo_asof(
                snapshots_previsao=[p], snapshots_rmm=[snapshot()])

    def test_nwp_capturado_apos_inicio_do_intervalo_bloqueia(self):
        p = nwp_snapshot(captured="2026-10-22T14:00:00Z")
        with self.assertRaisesRegex(ErroContextoMJO, "fuga temporal"):
            contextualizar_nwp_com_mjo_asof(
                snapshots_previsao=[p], snapshots_rmm=[snapshot()])

    def test_nwp_real_nao_homologado_tambem_e_bloqueado(self):
        p = nwp_snapshot()
        p["manifesto"]["classe"] = "REAL_AUTORIZADO"
        with self.assertRaisesRegex(ErroContextoMJO, "não autorizado"):
            contextualizar_nwp_com_mjo_asof(
                snapshots_previsao=[p], snapshots_rmm=[snapshot()])

    def test_nao_aceita_limite_de_idade_booleano(self):
        for n in [0, 15, True, None, 3.2]:
            with self.subTest(n=n), self.assertRaises(ErroContextoMJO):
                run(max_defasagem_dias=n)

    def test_usar_utc_com_offsets_sem_misturar_historicos(self):
        snap = snapshot()
        out = run(issues=[issue("OFFSET", "2026-10-20T11:00:00-04:00")],
                  snaps=[snap])
        self.assertEqual(out["contextos"][0]["status"], "RMM_OBSERVADO_ATIVO")
        self.assertEqual(out["contextos"][0]["emitido_em_utc"], "2026-10-20T15:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
