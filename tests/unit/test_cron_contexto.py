#!/usr/bin/env python3
"""Lo que el agente mandó por cron vuelve a su contexto — sin escribir en la sesión."""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kernel" / "bin"))
import cron  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.td = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.env = unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(self.td)})
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("KERNEL_CRON_JOB", None)
        self.ahora = datetime(2026, 9, 16, 9, 0, tzinfo=cron.TZ)

    def anota(self, task_id="seguimiento", texto="Seguimiento matutino: 3 órdenes en ruta",
              minutos=10, chat="-100000001"):
        cron.anotar_entrega(task_id, chat, texto, self.ahora - timedelta(minutes=minutos))


class TestLaBitacora(Base):
    def test_una_entrega_queda_anotada(self):
        self.anota()
        lineas = (self.td / cron.ENTREGAS).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lineas), 1)
        self.assertEqual(json.loads(lineas[0])["id"], "seguimiento")

    def test_se_recorta_el_texto_largo(self):
        self.anota(texto="x" * 5000)
        self.assertLessEqual(len(json.loads((self.td / cron.ENTREGAS).read_text())["texto"]),
                             cron.RECORTE)

    def test_no_crece_sin_límite(self):
        for i in range(cron.ENTREGAS_MAX + 20):
            self.anota(task_id=f"t{i}")
        self.assertEqual(len((self.td / cron.ENTREGAS).read_text().splitlines()),
                         cron.ENTREGAS_MAX)

    def test_si_no_puede_escribir_no_tumba_la_entrega(self):
        with unittest.mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": "/no/existe"}):
            cron.anotar_entrega("x", "1", "hola", self.ahora)   # no debe lanzar


class TestElContexto(Base):
    def test_cuenta_lo_que_la_sesion_no_vio(self):
        self.anota()
        texto = cron.contexto(self.ahora)
        self.assertIn("tareas programadas", texto)
        self.assertIn("Seguimiento matutino", texto)
        self.assertIn("-100000001", texto)

    def test_avisa_que_ya_se_entregó(self):
        """Sin esto, el agente puede reenviar el reporte creyendo que se le pidió."""
        self.anota()
        self.assertIn("no lo vuelvas a mandar", cron.contexto(self.ahora))

    def test_cada_entrega_se_cuenta_una_sola_vez(self):
        self.anota()
        self.assertTrue(cron.contexto(self.ahora))
        self.assertEqual(cron.contexto(self.ahora), "")

    def test_una_entrega_nueva_sí_se_cuenta(self):
        self.anota(minutos=30)
        cron.contexto(self.ahora)
        self.anota(task_id="vespertino", minutos=2)
        self.assertIn("vespertino", cron.contexto(self.ahora))

    def test_lo_viejo_ya_no_es_novedad(self):
        self.anota(minutos=60 * (cron.CONTEXTO_HORAS + 2))
        self.assertEqual(cron.contexto(self.ahora), "")

    def test_no_inunda_el_contexto(self):
        for i in range(cron.CONTEXTO_MAX + 6):
            self.anota(task_id=f"t{i}", minutos=i + 1)
        texto = cron.contexto(self.ahora)
        self.assertEqual(texto.count("· al chat"), cron.CONTEXTO_MAX)

    def test_sin_bitacora_no_dice_nada(self):
        self.assertEqual(cron.contexto(self.ahora), "")

    def test_callado_dentro_de_la_propia_tarea(self):
        """El `claude -p` del cron hereda los hooks; ahí esto no tiene sentido."""
        self.anota()
        with unittest.mock.patch.dict(os.environ, {"KERNEL_CRON_JOB": "1"}):
            self.assertEqual(cron.contexto(self.ahora), "")


class TestEnganchado(unittest.TestCase):
    def test_el_hook_esta_en_la_semilla(self):
        d = json.loads((ROOT / "kernel/managed-settings.json").read_text(encoding="utf-8"))
        args = [h.get("args") for b in d["hooks"]["UserPromptSubmit"] for h in b["hooks"]]
        self.assertIn(["/opt/kernel/bin/cron.py", "contexto"], args)

    def test_managed_settings_are_baked_root_owned(self):
        """Hooks live in managed settings: the image installs them where users cannot edit."""
        docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("/etc/claude-code/managed-settings.json", docker)

    def test_la_tarea_corre_marcada_como_tal(self):
        self.assertIn('KERNEL_CRON_JOB="1"', (ROOT / "kernel/bin/cron.py").read_text(encoding="utf-8"))

    def test_el_contexto_no_teclea_nada(self):
        """La regla del 15-sep: se añade contexto, no se escribe en la sesión."""
        fuente = (ROOT / "kernel/bin/cron.py").read_text(encoding="utf-8")
        self.assertNotIn("send-keys", fuente)


if __name__ == "__main__":
    unittest.main()
