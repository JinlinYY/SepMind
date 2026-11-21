"""Regression checks for publication data and metric denominators."""

from unittest import TestCase

from .tables import load_evidence, manuscript_tables


class PublicationTables(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = manuscript_tables(load_evidence())

    def test_reported_product_compositions(self):
        measured = [round(row["sepmind"], 4) for row in self.tables["table_01_products"]]
        self.assertEqual(measured, [99.9139, 0.1643, 99.8859, 99.8576, 93.6683, 2.0423, 99.5397, 0.0027])

    def test_benchmark_budget_and_missing_usage_are_preserved(self):
        a4 = [r for r in self.tables["architecture_and_ablation"] if r["configuration"] == "A4"]
        self.assertEqual([(r["revised_attempts_cap"], r["verified"], r["complete_token_runs"]) for r in a4],
                         [(3, 37, 40), (5, 38, 39), (3, 30, 40), (5, 30, 40)])
        self.assertTrue(all(r["design_setting"] == "Prescribed flowsheet design" for r in a4))
        self.assertEqual(len({r["numerical_protocol"] for r in a4}), 2)

    def test_paper_setting_ii_excludes_fixed_topology_statistics(self):
        table = self.tables["table_02_architectures"]
        self.assertEqual(len(table), 16)
        metrics = ("verified", "runs", "success_percent", "llm_calls_per_run", "llm_total_calls",
                   "strict_starts_per_run", "tokens_per_run", "complete_token_runs")
        for r in table:
            self.assertEqual(all(r[m] == "" for m in metrics), r["setting"] == "II")
            expected_name = "Autonomous flowsheet design" if r["setting"] == "II" else "Prescribed flowsheet design"
            self.assertEqual(r["design_setting"], expected_name)
        self.assertEqual(len(self.tables["autonomous_flowsheet_examples"]), 4)

    def test_reported_integrated_streams_and_recalculation(self):
        self.assertEqual(len(self.tables["table_03_integrated_products"]), 5)
        self.assertEqual(len(self.tables["table_S09_sulfolane_streams"]), 6)
        self.assertEqual(len(self.tables["table_S10_phenol_streams"]), 6)
        cooling = self.tables["table_S08_cooling_water_revision"]
        self.assertEqual([round(r["area_m2"], 4) for r in cooling], [60.7351, 57.3368])
        self.assertEqual(cooling[0]["duty_kW"], cooling[1]["duty_kW"])
