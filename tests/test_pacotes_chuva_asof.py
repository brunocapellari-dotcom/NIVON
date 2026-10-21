"""Ponte de previsões/observações: fixtures RAW sintéticas, sem HTTP."""
import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from nivon.pacotes_chuva_asof import (
    ErroPacoteChuva, montar_e_verificar_pares_chuva,
)


def pack(row, kind, capture, classe="SINTETICO"):
    raw = json.dumps({"registro": row}, sort_keys=True, separators=(",", ":")).encode()
    return {
        "manifesto": {
            "dataset_id": "NOAA_GFS" if kind == "PREVISAO" else "INMET_ESTACOES",
            "fonte_id": "NOAA" if kind == "PREVISAO" else "INMET",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "capturado_em": capture.isoformat(),
            "classe": classe,
            "prova_disponibilidade_sha256": hashlib.sha256(b"prova-sintetica").hexdigest(),
        },
        "bytes_json": raw,
    }


def data(n=36):
    forecasts = []
    observations = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        valid = base + timedelta(days=i + 5)
        issued = valid - timedelta(days=2)
        value = float([0, 2, 10, 20][i % 4])
        f = {
            "estacao_id": "INMET_A001", "produto_id": "GEFS_TESTE",
            "versao_produto": "versao-1",
            "emitido_em": issued.isoformat(),
            "previsao_publicada_em": (issued + timedelta(minutes=10)).isoformat(),
            "features_publicadas_ate": (issued - timedelta(hours=1)).isoformat(),
            "climatologia_publicada_em": (issued - timedelta(days=1)).isoformat(),
            "valido_em": valid.isoformat(), "membros_mm": [value] * 5,
            "prob_climatologica": 0.5,
        }
        o = {
            "estacao_id": "INMET_A001",
            "inicio_intervalo_em": (valid - timedelta(hours=24)).isoformat(),
            "fim_intervalo_em": valid.isoformat(),
            "observado_mm": value, "qc": "APROVADO",
            "qc_evidencia_sha256": hashlib.sha256(b"qc-sintetico").hexdigest(),
            "obs_publicado_em": (valid + timedelta(minutes=20)).isoformat(),
        }
        forecasts.append(pack(f, "PREVISAO", issued + timedelta(minutes=30)))
        observations.append(pack(o, "OBSERVACAO", valid + timedelta(hours=1)))
    return forecasts, observations


def run(fs, obs, **kwargs):
    args = dict(
        snapshots_previsao=fs, snapshots_observacao=obs,
        estacao_id="INMET_A001", produto_id="GEFS_TESTE",
        versao_produto="versao-1", horizonte_horas=48,
        acumulacao_horas=24, passo_horas=24,
        limiar_evento_mm=10, fonte_climatologia="CLIM_TESTE",
    )
    args.update(kwargs)
    return montar_e_verificar_pares_chuva(**args)


def update_payload(item, change):
    """Altera o JSON e atualiza hash para não mascarar erro semântico."""
    item = copy.deepcopy(item)
    obj = json.loads(item["bytes_json"].decode())
    change(obj["registro"])
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    item["bytes_json"] = raw
    item["manifesto"]["sha256"] = hashlib.sha256(raw).hexdigest()
    return item


class TestPacotesChuva(unittest.TestCase):
    def test_ponte_tem_pares_scores_e_hashes_sem_homologar(self):
        fs, obs = data()
        result = run(fs, obs)
        self.assertEqual(result["snapshots_previsao"], 36)
        self.assertEqual(result["snapshots_observacao"], 36)
        self.assertEqual(result["pacotes_raw_verificados_por_hash"], 72)
        self.assertAlmostEqual(result["avaliacao"]["brier"], 0)
        self.assertAlmostEqual(result["avaliacao"]["crps_medio_mm"], 0)
        self.assertFalse(result["homologado"])
        self.assertFalse(result["qc_instrumental_validado_independentemente"])
        self.assertFalse(result["avaliacao"]["homologado"])

    def test_tampering_hash_rejeitado(self):
        fs, obs = data()
        fs[1]["bytes_json"] += b" "
        with self.assertRaisesRegex(ErroPacoteChuva, "hash RAW"):
            run(fs, obs)

    def test_falta_observacao_rejeitada_sem_drop_silencioso(self):
        fs, obs = data()
        obs.pop(1)
        with self.assertRaisesRegex(ErroPacoteChuva, "não pareados"):
            run(fs, obs)

    def test_previsao_capturada_no_intervalo_rejeitada(self):
        fs, obs = data()
        valid = datetime.fromisoformat(json.loads(fs[2]["bytes_json"])["registro"]["valido_em"])
        fs[2]["manifesto"]["capturado_em"] = (valid - timedelta(hours=23)).isoformat()
        with self.assertRaisesRegex(ErroPacoteChuva, "antes do intervalo"):
            run(fs, obs)

    def test_observacao_duracao_errada_rejeitada(self):
        fs, obs = data()
        obs[3] = update_payload(obs[3], lambda r: r.update(
            inicio_intervalo_em="2025-12-01T00:00:00+00:00"))
        with self.assertRaisesRegex(ErroPacoteChuva, "duração"):
            run(fs, obs)

    def test_qc_declarado_reprovado_bloqueia(self):
        fs, obs = data()
        obs[5] = update_payload(obs[5], lambda r: r.update(qc="SUSPEITO"))
        with self.assertRaisesRegex(ErroPacoteChuva, "QC"):
            run(fs, obs)

    def test_mesma_estacao_produto_versao_obrigatorios(self):
        for kind, index, field, bad in [
            ("forecast", 4, "estacao_id", "INMET_B002"),
            ("forecast", 4, "versao_produto", "v2"),
            ("forecast", 4, "produto_id", "ERA5"),
            ("obs", 4, "estacao_id", "INMET_B002"),
        ]:
            fs, obs = data()
            target = fs if kind == "forecast" else obs
            target[index] = update_payload(target[index], lambda r: r.update({field: bad}))
            with self.subTest(kind=kind, field=field), self.assertRaises(ErroPacoteChuva):
                run(fs, obs)

    def test_nulo_nan_e_membros_faltantes_rejeitados(self):
        for value in [None, -1, "3", True, float("inf")]:
            fs, obs = data()
            obs[4] = update_payload(obs[4], lambda r: r.update(observado_mm=value))
            with self.subTest(value=value), self.assertRaises(ErroPacoteChuva):
                run(fs, obs)
        fs, obs = data()
        fs[5] = update_payload(fs[5], lambda r: r.update(membros_mm=[1, 2]))
        with self.assertRaisesRegex(ErroPacoteChuva, "membros"):
            run(fs, obs)

    def test_duplicate_json_keys_bloqueadas(self):
        fs, obs = data()
        raw = b'{"registro":{"foo":1,"foo":2}}'
        fs[0]["bytes_json"] = raw
        fs[0]["manifesto"]["sha256"] = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ErroPacoteChuva, "chave duplicada"):
            run(fs, obs)

    def test_futuros_arquivos_reais_requerem_catalogo_homologado(self):
        fs, obs = data()
        fs[0]["manifesto"]["classe"] = "REAL_AUTORIZADO"
        with self.assertRaises(PermissionError):
            run(fs, obs)
        catalogo = {"datasets": [
            {"id": "NOAA_GFS", "source_id": "NOAA",
             "enabled": False, "collection_authorized": False},
        ]}
        with self.assertRaises(PermissionError):
            run(fs, obs, catalogo=catalogo,
                autorizacoes=frozenset({"COLETA", "ARMAZENAMENTO", "PESQUISA"}),
                direitos_ref="EVIDENCIA_VALIDADA_EXTERNAMENTE")

    def test_revisoes_duplicadas_e_classe_mista_bloqueadas(self):
        fs, obs = data()
        fs[2] = copy.deepcopy(fs[1])
        with self.assertRaises(ErroPacoteChuva):
            run(fs, obs)
        fs, obs = data()
        obs[0]["manifesto"]["classe"] = "REAL_AUTORIZADO"
        with self.assertRaises(PermissionError):
            run(fs, obs)

    def test_snapshot_permissao_falsa_na_fixture_rejeitada(self):
        fs, obs = data()
        with self.assertRaisesRegex(ErroPacoteChuva, "fixture"):
            run(fs, obs, autorizacoes=frozenset({"COLETA"}))

    def test_fuso_invalido_e_observacao_publicada_antes_de_medida(self):
        fs, obs = data()
        obs[7] = update_payload(obs[7], lambda r: r.update(
            obs_publicado_em="2026-01-01T00:00:00+00:00"))
        with self.assertRaises(ErroPacoteChuva):
            run(fs, obs)
        fs, obs = data()
        fs[7]["manifesto"]["capturado_em"] = "2026-02-01T03:00:00"
        with self.assertRaises(ErroPacoteChuva):
            run(fs, obs)


if __name__ == "__main__":
    unittest.main()
