import unittest
from studio.analysis_speed import PRESETS, DEFAULT_PRESET, effective_budget

class AnalysisSpeedTests(unittest.TestCase):
 def test_all_presets(self):
  for name,(sec,multi) in PRESETS.items():
   got=effective_budget(name,120,5)
   self.assertEqual(got['seconds'],sec)
   self.assertEqual(got['multipv'],multi)
 def test_caps_are_enforced(self):
  got=effective_budget('deep',3,2)
  self.assertEqual((got['seconds'],got['multipv']),(3,2))
  self.assertTrue(got['limited_by_admin'])
 def test_unknown_preset_falls_back(self):
  self.assertEqual(effective_budget('not-valid',120,3)['preset'],DEFAULT_PRESET)
 def test_minimum_bound(self):
  got=effective_budget('turbo',-5,0)
  self.assertEqual((got['seconds'],got['multipv']),(1,1))
