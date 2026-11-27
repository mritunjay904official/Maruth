import unittest
from unittest.mock import patch

from drosophila_brain import run_drosophila_brain
from maruth.air_quality import CITY_PRESETS, get_city_air_quality, pm25_to_us_aqi
from maruth.impact_engine import calculate_impact_delta, get_default_interventions
from maruth.knowledge_base import search_smog_playbook
from maruth.schemas import HouseholdProfile


class TestSensorsAndImpact(unittest.TestCase):
    def test_presets_include_required_cities(self):
        self.assertIn("bolpur", CITY_PRESETS)
        self.assertIn("kolkata", CITY_PRESETS)
        self.assertIn("delhi_ncr", CITY_PRESETS)
        self.assertAlmostEqual(CITY_PRESETS["bolpur"].lat, 23.67, places=2)
        self.assertAlmostEqual(CITY_PRESETS["bolpur"].lon, 87.68, places=2)

    def test_drosophila_brain_backward_compat_and_threshold(self):
        low_res = run_drosophila_brain(air_data={"pm2_5": 35.0, "pm10": 55.0, "co": 400.0, "no2": 20.0})
        self.assertEqual(set(low_res.keys()), {"live_pm2_5", "neural_response", "detected_pm2_5", "status"})
        self.assertEqual(low_res["status"], "NORMAL")

        high_res = run_drosophila_brain(
            air_data={"pm2_5": 240.0, "pm10": 320.0, "co": 1400.0, "no2": 75.0},
            return_trace=True,
        )
        self.assertEqual(high_res["status"], "HIGH POLLUTION")
        self.assertGreater(high_res["detected_pm2_5"], 100.0)
        self.assertIn("trace", high_res)
        self.assertEqual(len(high_res["trace"]["neuron_rates_hz"]), 10)

    def test_us_aqi_breakpoints(self):
        aqi_good, cat_good, _ = pm25_to_us_aqi(8.0)
        self.assertLessEqual(aqi_good, 50)
        self.assertEqual(cat_good, "Good")

        aqi_haz, cat_haz, _ = pm25_to_us_aqi(260.0)
        self.assertGreater(aqi_haz, 300)
        self.assertEqual(cat_haz, "Hazardous")

    @patch("maruth.air_quality.get_live_air_quality", return_value=None)
    def test_air_quality_fallback_and_impact_physics(self, _mock_live):
        report = get_city_air_quality("delhi_ncr", force_refresh=True)
        self.assertEqual(report.data_source, "regional_fallback")
        self.assertGreater(report.pm2_5, 150.0)
        self.assertTrue(len(report.hourly_profile) >= 6)

        profile = HouseholdProfile(
            city_id="delhi_ncr",
            household_size=4,
            vulnerable_groups=["children", "asthma_copd"],
            home_sealing="drafty",
            cooking_fuel="biomass_wood",
            budget_tier="low_cost",
        )
        defaults = get_default_interventions(profile)
        impact = calculate_impact_delta(report, profile, defaults)
        self.assertLess(impact.projected_indoor_pm2_5, impact.baseline_indoor_pm2_5)
        self.assertGreater(impact.indoor_reduction_pct, 30.0)
        self.assertGreater(impact.community_pm25_emission_saved_g_day, 0.0)
        self.assertTrue(len(impact.causal_breakdown) >= 2)

    def test_rag_playbook_retrieval(self):
        docs = search_smog_playbook("diy box fan purifier budget", top_k=2)
        self.assertTrue(any("Corsi-Rosenthal" in d.title for d in docs))


if __name__ == "__main__":
    unittest.main()
