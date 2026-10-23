import unittest
from dataclasses import replace
from datetime import date,datetime,timezone
from hashlib import sha256

from nivon.historico import Observacao
from nivon.ivo_elegibilidade_rotulos import AtestacaoResultado,hash_observacao
from nivon.ivo_benchmark_atestado import executar_benchmark_sintetico_atestado

UTC=timezone.utc
P=sha256(b"parecer-sintetico-safra").hexdigest()
CORTE=datetime(2025,6,1,12,tzinfo=UTC)


def atestacoes():
    at=[]
    for y in range(2018,2025):
        for m in range(1,13):
            ny=y+int(m==12)
            nm=m%12+1
            doc=sha256(f"historico-sintetico-{y}-{m}".encode()).hexdigest()
            o=Observacao(fonte="FONTE_TESTE",variavel="PRODUCAO",
                produto="SOJA",regiao="MT",unidade="t",
                competencia=f"{y}-{m:02d}",calendario="MENSAL",
                referencia=date(y,m,1),publicacao=date(ny,nm,3),
                coleta=datetime(ny,nm,4,12,tzinfo=UTC),
                valor=float(100+5*(y-2018)+m),natureza="OBSERVADO",edicao=doc)
            at.append(AtestacaoResultado(
                observacao=o,dataset_id="TESTE_SERIE_SOJA",arquivo_sha256=doc,
                observacao_sha256=hash_observacao(o),
                classe_origem="MEDICAO_OBSERVADA",modalidade="SINTETICO",
                politica_resultado="MEDICAO_OBSERVADA",
                revisores=("AUDITOR_A","AUDITOR_B"),autor_modelo="IVO_CIENTISTA",
                parecer_sha256=P,direitos_ref="FONTE_FICTICIA_001",
                operacoes_aprovadas=frozenset({"ARMAZENAMENTO","ANALISE","TREINAMENTO"}),
                aprovado_em=datetime(2025,3,1,12,tzinfo=UTC)))
    return at


def executar(ats,**kw):
    args=dict(inicio="2024-01",fim="2024-06",corte_avaliacao=CORTE,
              autoriza_experimento=True,
              backend=lambda serie,h: float(serie[-1][1]+h))
    args.update(kw)
    return executar_benchmark_sintetico_atestado(ats,**args)


class TestIVOBenchmarkAtestado(unittest.TestCase):
    def test_serie_certificada_passa_por_seis_folds(self):
        r=executar(atestacoes())
        self.assertEqual(r["folds_validos"],6)
        self.assertEqual(r["tipo_dados"],"EXCLUSIVAMENTE_SINTETICO")
        self.assertEqual(r["edicoes_vintages"],84)
        self.assertFalse(r["real_data_allowed"])
        self.assertFalse(r["modelo_homologado"])
        self.assertEqual(len(r["pacote_atestacoes_sha256"]),64)

    def test_bloqueia_sem_aprovacao_explicita(self):
        with self.assertRaises(PermissionError):
            executar(atestacoes(),autoriza_experimento=False)

    def test_revisao_publicada_muito_tarde_nao_vaza_no_backtest(self):
        a=atestacoes()
        antigo=next(x for x in a if x.observacao.competencia=="2023-05")
        o=replace(antigo.observacao,valor=99999.,edicao="f"*64,
                  publicacao=date(2025,1,5),
                  coleta=datetime(2025,1,6,12,tzinfo=UTC))
        posterior=replace(antigo,observacao=o,arquivo_sha256=o.edicao,
                observacao_sha256=hash_observacao(o))
        original=executar(a)
        revisado=executar(a+[posterior])
        self.assertEqual(
            [f["hash_treino_asof"] for f in original["folds"]],
            [f["hash_treino_asof"] for f in revisado["folds"]])
        self.assertEqual(original["mae_modelo"],revisado["mae_modelo"])
        self.assertEqual(revisado["edicoes_vintages"],85)

    def test_projecao_nao_pode_ser_usada_mesmo_com_backend_de_teste(self):
        a=atestacoes()
        old=a[5]
        p=replace(old.observacao,natureza="PROJETADO")
        a[5]=replace(old,observacao=p,classe_origem="PROJETADO",
                     politica_resultado="PROJETADO",
                     observacao_sha256=hash_observacao(p))
        with self.assertRaises(PermissionError):
            executar(a)

    def test_real_autorizado_nao_vira_experimento_sintetico(self):
        a=atestacoes()
        a[0]=replace(a[0],modalidade="REAL_AUTORIZADO",dataset_id="CONAB_SAFRAS")
        with self.assertRaises(PermissionError):
            executar(a)


if __name__=="__main__":
    unittest.main()
