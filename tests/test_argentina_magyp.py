import json
import tempfile
import unittest
from pathlib import Path
from nivon.argentina_magyp import CATALOGO, RECURSO, coletar, selecionar, validar

HEADER = 'cultivo,anio,campania,provincia,provincia_id,departamento,departamento_id,superficie_sembrada_ha,superficie_cosechada_ha,produccion_tm,rendimiento_kgxha\n'
CSV = (HEADER + 'Soja,2024,2024/25,Cordoba,14,Capital,1,1,1,0,0\n').encode()
CAT = json.dumps({'success': True, 'result': {'license_id': 'CC-BY-4.0', 'resources': [{'id': RECURSO, 'format': 'CSV', 'url': 'https://datos.magyp.gob.ar/dataset/example.csv'}]}}).encode()

class TestArgentina(unittest.TestCase):
    def test_campanha_preservada(self):
        self.assertEqual(validar(CSV)['safras'], ['2024/25'])
    def test_esquema_e_linha_invalida(self):
        for raw in (b'<html>erro</html>', CSV + b'a,b\n'):
            with self.assertRaises(ValueError): validar(raw)
    def test_licenca_alterada(self):
        with self.assertRaises(ValueError): selecionar(CAT.replace(b'CC-BY-4.0', b'unknown'))
    def test_idempotencia_e_integridade(self):
        with tempfile.TemporaryDirectory() as tmp:
            def transporte(url, limite): return CAT if url == CATALOGO else CSV
            a = coletar(Path(tmp), transporte)
            b = coletar(Path(tmp), transporte)
            self.assertEqual(a, b)
            self.assertEqual(len(list(Path(tmp).iterdir())), 1)
            (Path(tmp)/a['sha256']/'estimaciones.csv').write_bytes(b'corrupt')
            with self.assertRaises(ValueError): coletar(Path(tmp), transporte)

if __name__ == '__main__': unittest.main()
