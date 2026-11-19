"""Offline tests: no network, no keys. Run: python -m unittest discover tests"""
import copy, json, os, sys, time, types, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from studio import script, packaging as P, learn

def llm_package(genre="crime"):
    sb = copy.deepcopy(script.BACKUPS[genre]); sb.update(copy.deepcopy(script.BACKUP_PACK[genre]))
    sb["topic_id"] = "fresh-topic"
    sb["hook_options"] = [dict(formula="x", text="Basically today I want to tell you guys about a secret."),
                          dict(formula="statistic", text="Eleven men. Rubber masks. Not a single shot fired."),
                          dict(formula="cold-open", text="Nobody heard the safe open. Nobody saw 2.7 million dollars leave.")]
    for s in sb["scenes"]:
        s.pop("beat", None)
    sb["scenes"][0]["narration"] = sb["hook_options"][0]["text"]            # deliberately weak scene-1 line
    return sb

class Packaging(unittest.TestCase):
    def test_ranks_good_over_filler(self):
        self.assertGreater(P.score_hook("He stole 2.7 million dollars and nobody ever found out who did it.")["verdict"],
                           P.score_hook("Basically today I want to tell you guys about an amazing secret.")["verdict"])
    def test_title_lint(self):
        self.assertTrue(P.lint_title("This Is An Absolutely Insane Amazing Secret Ultimate Trick That Nobody Knows About Yet")["issues"])
        self.assertEqual(P.lint_title("The 1950 Brink's Heist: 11 Men, Zero Shots", "NO ONE FIRED")["issues"], [])
    def test_thumb_never_repeats_title(self):
        t = P.clean_thumb_text("THE HEIST OF 1950 EXPLAINED NOW", "The 1950 Heist")
        self.assertLessEqual(len(t.split()), 3); self.assertNotIn("HEIST", t.split())
    def test_seo_shape(self):
        sb = script.backup_story("thriller", []); s = P.build_seo(sb)
        self.assertLessEqual(len(s["tags"]), 15); self.assertIn("#Shorts", s["hashtags"])
        self.assertEqual(s["description"].lower().count("fictional story"), 1)

class Script(unittest.TestCase):
    def test_normalize_swaps_in_stronger_hook_and_fills_beats(self):
        sb = script.normalize(llm_package(), "crime")
        self.assertNotIn("Basically", sb["scenes"][0]["narration"])
        self.assertEqual([sb["scenes"][0]["beat"], sb["scenes"][-1]["beat"]], ["hook", "loop"])
        self.assertTrue(any(s["beat"] == "turn" for s in sb["scenes"]))
        self.assertLessEqual(len(sb["thumb_text"].split()), 3)
        self.assertNotIn("hook_options", sb)
    def test_all_backups_valid(self):
        for g in script.GENRES:
            sb = script.backup_story(g, [])
            self.assertTrue(sb["hook_card"] and sb["thumb"]["text"] and sb["seo"]["queries"])
    def test_quota_error_does_not_sleep_and_skips_model(self):
        calls = []
        class Models:
            def generate_content(self, model, **kw):
                calls.append(model); raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
        fake = types.ModuleType("google.genai"); fake.Client = lambda api_key: types.SimpleNamespace(models=Models())
        google = types.ModuleType("google"); google.genai = fake
        sys.modules["google"], sys.modules["google.genai"] = google, fake
        os.environ["GEMINI_API_KEY"] = "x"; script._DEAD.clear(); script._init_budget({})
        t = time.time(); r = script._gemini_text("hi"); r2 = script._gemini_text("hi")
        self.assertIsNone(r); self.assertLess(time.time() - t, 1.0)
        self.assertEqual(len(calls), 3)                       # each of the 3 models is tried exactly once, never re-tried
        script._gemini_text("hi"); self.assertEqual(len(calls), 3)
        del os.environ["GEMINI_API_KEY"]
    def test_budget_cap(self):
        mem = {}; os.environ["GEMINI_DAILY_BUDGET"] = "2"; script._init_budget(mem)
        self.assertTrue(script._spend()); self.assertTrue(script._spend()); self.assertFalse(script._spend())
        del os.environ["GEMINI_DAILY_BUDGET"]
    def test_generate_story_uses_one_call_and_records_budget(self):
        os.environ.pop("FORCE_GENRE", None)
        n = {"c": 0}
        def fake(prompt, grounded=False, max_models=2):
            n["c"] += 1; return "Sure!\n" + json.dumps(llm_package("comedy"))
        orig = script._gemini_text; script._gemini_text = fake; os.environ["FORCE_GENRE"] = "comedy"
        try:
            mem = {"used_topics": []}; sb = script.generate_story(mem)
        finally:
            script._gemini_text = orig; del os.environ["FORCE_GENRE"]
        self.assertEqual(n["c"], 1); self.assertEqual(sb["topic_id"], "fresh-topic")
    def test_falls_back_to_backup_when_everything_fails(self):
        names = ("_gemini_text", "_github_models_text", "_pollinations_text")
        saved = {n: getattr(script, n) for n in names}
        for n in names:
            setattr(script, n, lambda *a, **k: None)
        os.environ["FORCE_GENRE"] = "thriller"
        try:
            sb = script.generate_story({"used_topics": []})
        finally:
            del os.environ["FORCE_GENRE"]
            for n, f in saved.items():
                setattr(script, n, f)
        self.assertEqual(sb["genre"], "thriller")

class Learn(unittest.TestCase):
    def test_learning_sets_weights(self):
        rows = [["a", 1000, 80, 30, 5], ["b", 900, 40, 12, 0], ["c", 800, 78, 28, 4]]
        class Q:
            def execute(self): return {"rows": rows}
        class Reports:
            def query(self, **k): return Q()
        api = types.SimpleNamespace(reports=lambda: Reports())
        gb = types.ModuleType("googleapiclient.discovery"); gb.build = lambda *a, **k: api
        sys.modules["googleapiclient.discovery"] = gb
        mem = {"published_log": {"a": dict(title="A", genre="crime", hook="h1"), "b": dict(title="B", genre="comedy", hook="h2"), "c": dict(title="C", genre="crime", hook="h3")}}
        hint = learn.learn_from_analytics(None, mem)
        self.assertGreater(mem["genre_weights"]["crime"], mem["genre_weights"]["comedy"]); self.assertIn("do not write hooks like", hint)

if __name__ == "__main__":
    unittest.main()
