from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "tatahome"


class ManifestTests(unittest.TestCase):
    def test_manifest(self) -> None:
        data = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(data["domain"], "tatahome")
        self.assertTrue(data["config_flow"])
        self.assertEqual(data["iot_class"], "cloud_polling")
        self.assertEqual(data["version"], "0.3.0")

    def test_translations_are_valid(self) -> None:
        for name in ("strings.json", "translations/en.json", "translations/zh-Hant.json"):
            json.loads((COMPONENT / name).read_text(encoding="utf-8"))

    def test_removed_experimental_features_are_absent(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in COMPONENT.glob("*.py")
        )
        self.assertNotIn("child_lock", source)
        self.assertNotIn("DeviceManualCtrl", source)
        self.assertNotIn("manual", source.lower().replace("manual_", ""))

    def test_settings_are_persisted_and_clean_modes_are_switches(self) -> None:
        self.assertTrue((COMPONENT / "storage.py").exists())
        self.assertFalse((COMPONENT / "button.py").exists())
        self.assertIn("edge_clean", (COMPONENT / "switch.py").read_text(encoding="utf-8"))
        self.assertIn(
            "PERCENTAGE",
            (COMPONENT / "sensor.py").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
