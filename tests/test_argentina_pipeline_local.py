"""Pipeline ARG com metadados, bytes e banco sintéticos (sem rede)."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from nivon.argentina_agricultura import ErroArgentina, RECURSOS
from nivon.argentina_pipeline_local import coletar_estimativas_local, guardar_raw_privado

URL='https://datos.magyp.gob.ar/dataset/soja-siembra-cosecha-produccion-rendimiento/resource/ba694aa3-99d2-4d7d-9936-60f88e36ad9a/download/soja.csv'
CSV=('cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n'
     'Soja,2025,2025/26,Cordoba,014,Capital,00010,100,90,270,3000\n').encode()
SHA=sha256(CSV).hexdigest()

def _metadata(recurso,executar=False):
    assert executar
    return {'recurso':recurso,'id':RECURSOS[recurso],
            'url_candidata_nao_autorizada':URL}

def _csv(**kwargs):
    assert kwargs['executar'] and kwargs['direitos_coleta_verificados']
    return {'recurso':'soja','fonte_url':URL,'sha256':SHA,'raw':CSV,
            'coletado_em':'2026-10-22T16:00:00+00:00'}

class TestPipelineArgentina(unittest.TestCase):
    def test_pipeline_quarentena_e_idempotencia(self):
        with TemporaryDirectory() as pasta:
            kw={'recurso':'soja','banco':Path(pasta)/'sqlite.db',
                'pasta_raw':Path(pasta)/'privados',
                'executar':True,'direitos_coleta_verificados':True,
                'direitos_armazenamento_verificados':True,
                'buscar_metadados':_metadata,'buscar_csv':_csv}
            a=coletar_estimativas_local(**kw)
            self.assertEqual(a['sha256'],SHA)
            self.assertFalse(a['apto_publicacao'])
            self.assertEqual(Path(a['raw_privado']).read_bytes(),CSV)
            self.assertEqual(Path(a['raw_privado']).stat().st_mode & 0o777,0o600)
            b=coletar_estimativas_local(**kw)
            self.assertEqual(b['status'],'DUPLICATA_IDEMPOTENTE')
            with sqlite3.connect(kw['banco']) as db:
                self.assertEqual(db.execute('select count(*) from ar_estimaciones').fetchone()[0],1)
                self.assertEqual(db.execute('select publicado_utc from ar_ediciones').fetchone()[0],None)

    def test_direitos_explicitos(self):
        with TemporaryDirectory() as pasta:
            with self.assertRaises(PermissionError):
                coletar_estimativas_local(recurso='soja',banco=Path(pasta)/'db',
                    pasta_raw=Path(pasta)/'r',buscar_metadados=_metadata,buscar_csv=_csv)

    def test_bytes_trocados_nao_entram_em_banco(self):
        with TemporaryDirectory() as pasta:
            def adulterado(**kwargs):
                r=_csv(**kwargs)
                return {**r,'sha256':sha256(b'outro').hexdigest()}
            with self.assertRaises(ErroArgentina):
                coletar_estimativas_local(recurso='soja',banco=Path(pasta)/'db',
                    pasta_raw=Path(pasta)/'r',executar=True,
                    direitos_coleta_verificados=True,direitos_armazenamento_verificados=True,
                    buscar_metadados=_metadata,buscar_csv=adulterado)
            self.assertFalse((Path(pasta)/'db').exists())

    def test_raw_privado_impede_modificacao(self):
        with TemporaryDirectory() as pasta:
            raw=Path(pasta)/'raw'
            endereco=guardar_raw_privado(dados=CSV,pasta=raw,digest=SHA)
            Path(endereco).write_bytes(b'adulterado')
            with self.assertRaises(ErroArgentina):
                guardar_raw_privado(dados=CSV,pasta=raw,digest=SHA)

    def test_origem_divergente_bloqueada(self):
        with TemporaryDirectory() as pasta:
            def adulterado(recurso,executar=False):
                return {**_metadata(recurso,executar),'id':'id-errado'}
            with self.assertRaises(ErroArgentina):
                coletar_estimativas_local(recurso='soja',banco=Path(pasta)/'db',
                    pasta_raw=Path(pasta)/'r',executar=True,
                    direitos_coleta_verificados=True,direitos_armazenamento_verificados=True,
                    buscar_metadados=adulterado,buscar_csv=_csv)

if __name__=='__main__':
    unittest.main()
