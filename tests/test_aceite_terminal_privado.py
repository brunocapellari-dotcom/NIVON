"""Aceitação integrada de Cloud Run privado com fonte real e limites de custo.

Não cria recursos, não acessa rede, não usa GCP; entradas são evidências
simuladas e contratos reais do servidor NIVON.
"""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nivon.aceite_terminal_privado import conferir_aceite_terminal, conferir_politica_iap, FalhaAceite
from nivon.terminal_web import interpretar_serie

NOW=datetime(2026,10,25,20,0,tzinfo=timezone.utc)
SHA="a"*40
REV="nivon-terminal-00017-abc"

def service():
    return {
        "metadata":{"name":"nivon-terminal","labels":{"nivon-component":"terminal"}},
        "iapEnabled":True,
        "spec":{"template":{"spec":{
            "serviceAccountName":"nivon-terminal-readonly@nivon-data.iam.gserviceaccount.com",
            "containers":[{"image":
              "southamerica-east1-docker.pkg.dev/nivon-data/imagens/nivon-terminal:"+SHA[:12]}]
        }}},
        "status":{
            "url":"https://nivon-terminal-example-southamerica-east1.a.run.app",
            "latestReadyRevisionName":REV,
            "conditions":[{"type":"Ready","status":"True"}],
            "traffic":[{"revisionName":REV,"percent":100}],
        },
    }


def data():
    rows=[
        {"ano":i,"registros":120,"tu":"10000",
         "ultima_competencia":str(i)+("-08" if i==2026 else "-12"),
         "versoes_sha":1,"ultima_coleta":NOW}
        for i in range(2006,2027)
    ]
    doc=interpretar_serie(rows,ultimo_ano=2026,agora=NOW)
    doc["bytes_processados_ultimo_job"]=4_000_000
    return doc


def options():
    return {
        "service":service(),
        "iam":{"bindings":[{"role":"roles/run.invoker",
                             "members":["serviceAccount:service-123456789012@gcp-sa-iap.iam.gserviceaccount.com"]}]},
        "health":{"estado":"PROCESSO_ATIVO"},
        "dados":data(),
        "unauth_status":"403",
        "commit_sha":SHA,
        "agora":NOW,
        "numero_projeto":"123456789012",
    }


class TestAceiteTerminalPrivado(unittest.TestCase):
    def test_aceite_reconcilia_dado_antt_real_contrato_iam_e_revisao(self):
        doc=conferir_aceite_terminal(**options())
        self.assertEqual(doc["estado"],"GO_LIVE_PRIVADO_01_ACEITE_TECNICO")
        self.assertTrue(doc["iam_sem_publico"])
        self.assertTrue(doc["acesso_sem_token_rejeitado"])
        self.assertTrue(doc["ferrovia_bq_autenticado"])
        self.assertEqual(doc["ultima_competencia"],"2026-08")
        self.assertEqual(doc["anos_observados"],21)
        self.assertFalse(doc["custos_totais_zerados_comprovados"])
        self.assertFalse(doc["homologacao_editorial"])

    def test_proibe_anyone_ou_todos_autenticados_no_iam(self):
        for member in ("allUsers","allAuthenticatedUsers"):
            kw=options()
            kw["iam"]["bindings"][0]["members"].append(member)
            with self.subTest(member=member),self.assertRaisesRegex(
                FalhaAceite,"público"):
                conferir_aceite_terminal(**kw)

    def test_anonimo_200_nao_e_privado(self):
        kw=options()
        kw["unauth_status"]="200"
        with self.assertRaisesRegex(FalhaAceite,"não foi negado"):
            conferir_aceite_terminal(**kw)

    def test_imagem_de_outro_commit_ou_outra_regiao_reprovada(self):
        for image in ("southamerica-east1-docker.pkg.dev/nivon-data/imagens/nivon-terminal:deadbeefdead",
                      "us-central1-docker.pkg.dev/nivon-data/imagens/nivon-terminal:"+SHA[:12]):
            kw=options()
            kw["service"]["spec"]["template"]["spec"]["containers"][0]["image"]=image
            with self.subTest(image=image),self.assertRaises(FalhaAceite):
                conferir_aceite_terminal(**kw)

    def test_so_revisao_ready_com_100_porcento_recebe_aceite(self):
        cases=[
            lambda x:x["status"]["traffic"][0].update(percent=90),
            lambda x:x["status"].update(latestReadyRevisionName=""),
            lambda x:x["status"].update(conditions=[{"type":"Ready","status":"False"}]),
        ]
        for mutate in cases:
            kw=options()
            mutate(kw["service"])
            with self.subTest(service=kw["service"]["status"]),self.assertRaises(FalhaAceite):
                conferir_aceite_terminal(**kw)

    def test_nao_aceita_url_externa_credencial_embutida_ou_http(self):
        for url in ("https://evil.example.com", "http://nivon-terminal.a.run.app",
                    "https://me:pwd@nivon-terminal.a.run.app",
                    "https://nivon-terminal.a.run.app:8443/",
                    "https://nivon-terminal.a.run.app/api/v1/ferrovia"):
            kw=options()
            kw["service"]["status"]["url"]=url
            with self.subTest(url=url),self.assertRaises(FalhaAceite):
                conferir_aceite_terminal(**kw)

    def test_total_fabricado_e_competencia_futura_reprovados(self):
        for change in (
            lambda d:d.update(tu_acumuladas="210001"),
            lambda d:d["serie"][-1].update(ultima_competencia="2026-12"),
            lambda d:d["serie"][2].update(toneladas_uteis="0"),
            lambda d:d["serie"].pop(3),
            lambda d:d.update(homologacao_editorial=True),
        ):
            kw=options()
            change(kw["dados"])
            with self.assertRaises(FalhaAceite):
                conferir_aceite_terminal(**kw)

    def test_consulta_acima_limite_250_mb_bloqueada(self):
        kw=options()
        kw["dados"]["bytes_processados_ultimo_job"]=250_000_001
        with self.assertRaisesRegex(FalhaAceite,"orçamento"):
            conferir_aceite_terminal(**kw)

    def test_health_status_nao_substitui_antt(self):
        kw=options()
        kw["dados"]={"estado":"FONTE_TEMPORARIAMENTE_INDISPONIVEL"}
        with self.assertRaises(FalhaAceite):
            conferir_aceite_terminal(**kw)

    def test_cli_offline_valida_documentos_no_disco_sem_credenciais(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            kw=options()
            for key in ("service","iam","health","dados"):
                (root/(key+".json")).write_text(json.dumps(
                    kw[key],ensure_ascii=False),encoding="utf-8")
            cmd=[sys.executable,"-m","nivon.aceite_terminal_privado",
                 "--service",str(root/"service.json"),
                 "--iam",str(root/"iam.json"),
                 "--health",str(root/"health.json"),
                 "--dados",str(root/"dados.json"),
                 "--unauth-status","403","--commit-sha",SHA,
                 "--numero-projeto","123456789012"]
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn("GO_LIVE_PRIVADO_01_ACEITE_TECNICO",result.stdout)
            # CLI não depende de segredo e deve rejeitar IAM público.
            bad=json.loads((root/"iam.json").read_text())
            bad["bindings"][0]["members"]=["allUsers"]
            (root/"iam.json").write_text(json.dumps(bad))
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=12)
            self.assertEqual(result.returncode,2)
            self.assertIn("NAO_HOMOLOGADO",result.stdout)

    def test_iap_desativado_falha(self):
        kw=options()
        kw["service"]["iapEnabled"]=False
        with self.assertRaisesRegex(FalhaAceite,"IAP"):
            conferir_aceite_terminal(**kw)

    def test_invoker_iap_correto_obrigatorio(self):
        kw=options()
        kw["iam"]["bindings"][0]["members"]=["serviceAccount:outra@nivon-data.iam.gserviceaccount.com"]
        with self.assertRaisesRegex(FalhaAceite,"agente IAP"):
            conferir_aceite_terminal(**kw)

    def test_403_sem_identidade_e_requerido_no_aceite_m1(self):
        for status in ("200", "302", "500"):
            kw=options()
            kw["unauth_status"]=status
            with self.subTest(status=status),self.assertRaises(FalhaAceite):
                conferir_aceite_terminal(**kw)
        self.assertTrue(conferir_aceite_terminal(**options())["acesso_sem_token_rejeitado"])

    def test_iam_publico_em_qualquer_binding_reprovado(self):
        kw=options()
        kw["iam"]["bindings"].append({"role":"roles/viewer","members":["allAuthenticatedUsers"]})
        with self.assertRaises(FalhaAceite):
            conferir_politica_iap(kw["service"],kw["iam"],kw["numero_projeto"])

if __name__=="__main__":
    unittest.main()
