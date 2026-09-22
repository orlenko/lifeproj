import json
import tempfile
import unittest
from pathlib import Path

from lifeproj import cli, menu, registry, tui


def press(m, *keys):
    """Feed keys to a menu: a Key, or a character as shorthand."""
    for k in keys:
        m.handle(k if isinstance(k, tui.Key) else tui.Key(tui.KEY_CHAR, k))


UP = tui.Key(tui.KEY_UP)
DOWN = tui.Key(tui.KEY_DOWN)
LEFT = tui.Key(tui.KEY_LEFT)
RIGHT = tui.Key(tui.KEY_RIGHT)
ENTER = tui.Key(tui.KEY_ENTER)
ESC = tui.Key(tui.KEY_ESC)
SPACE = tui.Key(tui.KEY_CHAR, " ")


def focus_on(m, key):
    """Walk the focus down to a row by key, the way a hand would."""
    for _ in range(len(m.rows())):
        if m.focus[m.screen] == key:
            return
        press(m, DOWN)
    raise AssertionError(f"never reached {key}: {[r.key for r in m.rows()]}")


def env_with(*names, root=None, home=None, archived=()):
    e = menu.Env(root=Path(root) if root else None,
                 home=Path(home) if home else None)
    for n in names:
        e.tekas.append(menu.Teka(n, Path(f"/w/{n}"), Path(f"/enc/{n}"), exists=True))
    for n in archived:
        e.tekas.append(menu.Teka(n, Path(f"/w/{n}"), Path(f"/enc/{n}"), archived=True))
    e.loaded = True
    return e


class NewArgsTests(unittest.TestCase):
    def _args(self, **kw):
        return " ".join(menu.new_args(menu.Choice(name="mila", **kw)))

    def test_composes_the_friendly_flags(self):
        for kw, want in [
            ({}, "new mila"),
            ({"domain": "tenancy"}, "new mila --domain tenancy"),
            ({"lifecycle": "finite"}, "new mila --lifecycle finite"),
            ({"summary": "the Mila file"}, "new mila --summary the Mila file"),
            ({"intake": ["docs", "email"]}, "new mila --intake email,docs"),
            ({"artifact": ["ledger", "timeline"]}, "new mila --artifact timeline,ledger"),
            ({"intake": ["email"], "imap_folder": "Personal/Mila"},
             "new mila --intake email --imap-folder Personal/Mila"),
            ({"artifact": ["chapters"], "chapter_noun": "tenancy"},
             "new mila --artifact chapters --chapter-noun tenancy"),
            ({"path": "~/work/mila"}, "new mila --path ~/work/mila"),
            ({"register": False}, "new mila --no-register"),
            ({"dry_run": True}, "new mila --dry-run"),
        ]:
            self.assertEqual(self._args(**kw), want, kw)

    def test_detail_of_a_module_that_is_off_is_not_passed(self):
        # The rows stay filled in while you toggle modules back and forth; only
        # what the chosen modules actually use reaches the command line.
        self.assertEqual(self._args(imap_folder="Personal/Mila", chapter_noun="tenancy"),
                         "new mila")

    def test_chips_keep_their_canonical_order(self):
        self.assertEqual(self._args(intake=["github", "docs", "email"]),
                         "new mila --intake email,docs,github")


class TekaArgsTests(unittest.TestCase):
    def test_actions_address_the_teka_the_way_the_cli_does(self):
        t = menu.Teka("mila", Path("/w/mila"), Path("/enc/mila"))
        self.assertEqual(menu.teka_args("publish", t), ["publish", "--path", "/w/mila"])
        self.assertEqual(menu.teka_args("drain", t), ["drain", "--path", "/w/mila"])
        self.assertEqual(menu.teka_args("equip", t), ["equip", "mila"])
        self.assertEqual(menu.teka_args("archive", t), ["archive", "mila"])
        self.assertEqual(menu.teka_args("restore", t), ["restore", "mila"])


class ComposedCommandsParseTests(unittest.TestCase):
    """The menu may only compose commands the CLI already understands."""

    def _parses(self, argv):
        args = cli.build_parser().parse_args(argv)
        self.assertTrue(callable(args.func), argv)
        return args

    def test_every_new_command_parses(self):
        for domain in menu.DOMAINS:
            for lifecycle in menu.LIFECYCLES:
                for register in (True, False):
                    c = menu.Choice(
                        name="mila", domain=domain, lifecycle=lifecycle,
                        summary="one line", intake=list(menu.INTAKE),
                        artifact=list(menu.ARTIFACTS), path="~/personal/mila",
                        imap_folder="Personal/Mila", chapter_noun="tenancy",
                        register=register, dry_run=True)
                    args = self._parses(menu.new_args(c))
                    self.assertEqual(args.domain, domain)
                    self.assertEqual(args.intake, list(menu.INTAKE))
                    self.assertEqual(args.artifact, list(menu.ARTIFACTS))

    def test_every_chip_names_a_real_module(self):
        from lifeproj.modules import MODULES
        for chip, module in menu.CHIP_MODULE.items():
            self.assertIn(module, MODULES, chip)
        self.assertEqual(set(menu.INTAKE), set(cli.INTAKE_MAP))
        self.assertEqual(set(menu.ARTIFACTS) | {"catalog"}, set(cli.ARTIFACT_MAP))

    def test_every_domain_overlay_is_offered_and_explained(self):
        from lifeproj.modules import OVERLAYS
        for domain in OVERLAYS:
            self.assertIn(domain, menu.DOMAINS)
            self.assertIn("overlay", menu.domain_hint(domain))
        for domain in menu.DOMAINS:
            self.assertTrue(menu.domain_hint(domain))
        # A domain with no overlay says so rather than inventing one.
        self.assertIn("No", menu.domain_hint("tax"))

    def test_every_teka_and_home_command_parses(self):
        m = menu.Menu(env_with("mila", archived=("old",)))
        for row in m.rows():
            if row.key.startswith("teka:"):
                continue
            m.focus["home"] = row.key
            if m.command():
                self._parses(m.command())
        for name in ("mila", "old"):
            m.teka_name, m.screen = name, "teka"
            for row in m.rows():
                if row.key == "back" or row.off:
                    continue
                m.focus["teka"] = row.key
                self._parses(m.command())


class KeyTests(unittest.TestCase):
    def test_parses_escape_sequences_and_text(self):
        keys = tui.parse_keys(b"\x1b[A\x1b[B\x1b[C\x1b[D\r\x7fab\x1b")
        self.assertEqual([k.code for k in keys],
                         [tui.KEY_UP, tui.KEY_DOWN, tui.KEY_RIGHT, tui.KEY_LEFT,
                          tui.KEY_ENTER, tui.KEY_BACKSPACE, tui.KEY_CHAR,
                          tui.KEY_CHAR, tui.KEY_ESC])
        self.assertEqual("".join(k.char for k in keys), "ab")

    def test_unknown_sequences_do_not_leak_as_text(self):
        self.assertEqual(tui.parse_keys(b"\x1b[200~"), [])
        self.assertEqual(tui.parse_keys(b"\x1b[5"), [])      # incomplete

    def test_multibyte_text_survives(self):
        self.assertEqual([k.char for k in tui.parse_keys("é".encode())], ["é"])


class MenuFlowTests(unittest.TestCase):
    def test_typing_a_name_and_toggling_modules_composes_the_command(self):
        m = menu.Menu(env_with("mila"))
        press(m, ENTER)                              # New teka
        self.assertEqual(m.screen, "new")
        press(m, SPACE)                              # edit the name
        press(m, "b", "o", "r", "e", "y")
        press(m, ENTER)                              # commit; focus moves on
        self.assertEqual(m.c.name, "borey")
        self.assertEqual(m.focus["new"], "domain")
        press(m, RIGHT, RIGHT)                       # general -> legal -> tenancy
        press(m, DOWN, DOWN, DOWN)                   # lifecycle, summary, intake
        self.assertEqual(m.focus["new"], "intake")
        press(m, SPACE)                              # email on
        press(m, RIGHT, SPACE)                       # docs on
        press(m, DOWN, RIGHT, SPACE)                 # artifacts: ledger on
        self.assertEqual(menu.preview(m.command()),
                         "lifeproj new borey --domain tenancy --intake email,docs"
                         " --artifact ledger")
        done = m.handle(ENTER)
        self.assertEqual(done.args, m.command() or done.args)
        self.assertEqual(done.args[:2], ["new", "borey"])

    def test_enter_without_a_name_asks_for_one_instead_of_running(self):
        m = menu.Menu(env_with())
        press(m, ENTER)
        self.assertIsNone(m.handle(ENTER))
        self.assertEqual(m.focus["new"], "name")
        self.assertEqual(m.editing, "name")
        self.assertIn("name", m.note.lower())

    def test_escape_while_typing_keeps_the_old_value(self):
        m = menu.Menu(env_with(), menu.Choice(name="mila"))
        m.screen = "new"
        press(m, SPACE, "x", ESC)
        self.assertEqual(m.c.name, "mila")
        self.assertEqual(m.editing, "")

    def test_rows_that_do_not_apply_are_skipped_and_explained(self):
        m = menu.Menu(env_with())
        m.screen, m.expanded = "new", True
        rows = {r.key: r for r in m.rows()}
        self.assertEqual(rows["imap_folder"].off, "email intake is off")
        self.assertEqual(rows["chapter_noun"].off, "the chapters module is off")
        m.focus["new"] = "artifact"
        m._move(1)                                   # first applicable More row
        self.assertEqual(m.focus["new"], "path")
        m.c.intake.append("email")
        m.focus["new"] = "artifact"
        m._move(1)
        self.assertEqual(m.focus["new"], "imap_folder")

    def test_a_teka_opens_its_own_actions(self):
        m = menu.Menu(env_with("mila"))
        focus_on(m, "teka:mila")
        press(m, ENTER)
        self.assertEqual((m.screen, m.teka_name), ("teka", "mila"))
        self.assertEqual(m.command(), ["publish", "--path", "/w/mila"])
        press(m, ESC)
        self.assertEqual(m.screen, "home")

    def test_a_teka_without_a_local_copy_offers_only_what_can_run(self):
        e = env_with("mila")
        e.teka("mila").exists = False
        m = menu.Menu(e)
        m.screen, m.teka_name = "teka", "mila"
        rows = {r.key: r.off for r in m.rows()}
        self.assertTrue(rows["publish"] and rows["drain"] and rows["equip"])
        self.assertFalse(rows["archive"])

    def test_opening_a_teka_focuses_something_it_can_actually_run(self):
        # Nothing local to publish, drain or equip: restore is the whole point.
        e = env_with("mila")
        e.teka("mila").exists = False
        m = menu.Menu(e)
        focus_on(m, "teka:mila")
        press(m, ENTER)
        self.assertEqual(m.focus["teka"], "restore")
        self.assertEqual(m.command(), ["restore", "mila"])

    def test_restore_all_appears_only_when_a_teka_is_missing(self):
        e = env_with("mila", "condo")
        m = menu.Menu(e)
        self.assertNotIn("restore_all", [r.key for r in m.rows()])
        e.teka("condo").exists = False
        m = menu.Menu(e)
        row = next(r for r in m.rows() if r.key == "restore_all")
        self.assertIn("1 registered teka with no local copy", row.desc)
        m.focus["home"] = "restore_all"
        self.assertEqual(m.command(), ["restore", "--all"])
        self.assertIn("--old-home", m.hint(m.current()))

    def test_the_teka_home_is_offered_and_sets_the_default_path(self):
        m = menu.Menu(env_with(home="/tekas"), menu.Choice(name="mila"))
        row = next(r for r in m.rows() if r.key == "home")
        self.assertEqual(row.desc, "/tekas")
        m.focus["home"] = "home"
        self.assertEqual(m.command(), ["home"])
        m.screen = "new"
        self.assertEqual(m._default_path(), "/tekas/mila")
        # Unset, `lifeproj new` falls back to ~/personal and so does the form.
        m2 = menu.Menu(env_with(), menu.Choice(name="mila"))
        self.assertEqual(m2._default_path(), "~/personal/mila")

    def test_a_name_the_cli_would_reject_never_reaches_it(self):
        for bad in ("", ".", "..", "a/b", "/abs"):
            self.assertFalse(menu.valid_name(bad), bad)
            m = menu.Menu(env_with(), menu.Choice(name=bad))
            m.screen = "new"
            self.assertIsNone(m.command(), bad)
            self.assertIsNone(m.handle(ENTER), bad)
            self.assertEqual(m.editing, "name", bad)
        self.assertTrue(menu.valid_name("tenants-123main"))

    def test_an_archived_teka_offers_restore_instead_of_archive(self):
        m = menu.Menu(env_with(archived=("old",)))
        m.screen, m.teka_name = "teka", "old"
        keys = [r.key for r in m.rows()]
        self.assertIn("restore", keys)
        self.assertNotIn("archive", keys)

    def test_quitting_returns_nothing_to_run(self):
        m = menu.Menu(env_with())
        self.assertEqual(m.handle(tui.Key(tui.KEY_CHAR, "q")).args, None)
        self.assertEqual(menu.Menu(env_with()).handle(ESC).args, None)

    def test_ctrl_c_quits_from_any_screen(self):
        for screen in ("home", "new", "teka"):
            m = menu.Menu(env_with("mila"))
            m.screen, m.teka_name = screen, "mila"
            done = m.handle(tui.Key(tui.KEY_QUIT))
            self.assertIsNotNone(done, screen)
            self.assertIsNone(done.args, screen)

    def test_escape_backs_out_one_screen_at_a_time(self):
        m = menu.Menu(env_with("mila"))
        m.screen, m.teka_name = "teka", "mila"
        self.assertIsNone(m.handle(ESC))
        self.assertEqual(m.screen, "home")
        self.assertIsNotNone(m.handle(ESC))

    def test_help_is_the_cli_usage(self):
        self.assertEqual(menu.Menu(env_with()).handle(tui.Key(tui.KEY_CHAR, "?")).args,
                         ["--help"])


class RenderTests(unittest.TestCase):
    def _lines(self, m, w=80, h=24):
        return ["".join(s.text for s in line) for line in m.render(w, h)]

    def test_home_shows_every_teka_and_where_things_live(self):
        m = menu.Menu(env_with("mila", "condo", root="/enc", home="/tekas",
                               archived=("old",)))
        text = "\n".join(self._lines(m))
        for word in ("mila", "condo", "old", "New teka", "/enc", "/tekas"):
            self.assertIn(word, text)

    def test_the_focused_module_explains_itself(self):
        m = menu.Menu(env_with())
        m.screen, m.focus["new"] = "new", "intake"
        hint = m.hint(m.current())
        self.assertIn("email", hint)
        self.assertIn("IMAP label", hint)

    def test_narrow_terminals_still_draw(self):
        m = menu.Menu(env_with("mila", root="/enc"))
        for screen in ("home", "new", "teka"):
            m.screen, m.teka_name, m.expanded = screen, "mila", True
            for w in (24, 40, 200):
                for line in m.render(w, 10):
                    clipped = tui.clip(line, w)
                    self.assertLessEqual(tui.cells("".join(s.text for s in clipped)), w)

    def test_wrap_and_pad_measure_in_cells(self):
        self.assertEqual(tui.wrap("one two three", 8), ["one two", "three"])
        self.assertEqual(tui.pad("ab", 5), "ab   ")
        self.assertEqual(tui.truncate("abcdef", 4), "abc…")


class StateTests(unittest.TestCase):
    def test_remembers_the_shape_but_never_the_teka(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "menu.json"
            c = menu.Choice(name="mila", summary="s", domain="tenancy",
                            intake=["email"], artifact=["ledger"],
                            imap_folder="Personal/Mila", path="~/x", dry_run=True)
            menu.save_choice(c, path)
            saved = json.loads(path.read_text())
            for gone in ("name", "summary", "imap_folder", "path", "dry_run"):
                self.assertNotIn(gone, saved)
            back = menu.load_choice(path)
            self.assertEqual((back.domain, back.intake, back.artifact),
                             ("tenancy", ["email"], ["ledger"]))
            self.assertEqual(back.name, "")

    def test_a_missing_or_corrupt_state_file_is_just_the_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "menu.json"
            self.assertEqual(menu.load_choice(path), menu.Choice())
            path.write_text("{not json")
            self.assertEqual(menu.load_choice(path), menu.Choice())
            path.write_text('{"domain": "nope", "intake": ["email", "mars"]}')
            back = menu.load_choice(path)
            self.assertEqual((back.domain, back.intake), ("general", ["email"]))


class EnvironmentTests(unittest.TestCase):
    def test_reads_both_registry_sections_without_touching_the_tekas(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.toml"
            doc = registry.load(cfg)
            registry.add(doc, "mila", "~/personal/mila", "/enc/mila", imap_folder="P/Mila")
            registry.add(doc, "old", "~/personal/old", "/enc/old")
            registry.archive(doc, "old")
            registry.set_encrypted_root(doc, Path("/enc"))
            registry.save(doc, cfg)

            env = menu.environment(cfg)
            self.assertEqual([t.name for t in env.tekas], ["mila", "old"])
            self.assertEqual(env.teka("mila").imap_folder, "P/Mila")
            self.assertTrue(env.teka("old").archived)
            self.assertEqual(env.root, Path("/enc"))
            # Opening the menu looks at no teka's contents.
            self.assertIsNone(env.teka("mila").intake)
            self.assertFalse(env.loaded)

    def test_enrich_fills_in_intake_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            wd, ed = tmp / "mila", tmp / "enc" / "mila"
            (wd / "intake").mkdir(parents=True)
            (wd / "intake" / "a.md").write_text("x")
            ed.mkdir(parents=True)
            (ed / "manifest.age").write_text("x")
            cfg = tmp / "config.toml"
            doc = registry.load(cfg)
            registry.add(doc, "mila", str(wd), str(ed))
            registry.save(doc, cfg)

            env = menu.enrich(menu.environment(cfg))
            self.assertTrue(env.loaded)
            self.assertEqual(env.teka("mila").intake, 1)
            self.assertTrue(env.teka("mila").backup.endswith("ago"))


if __name__ == "__main__":
    unittest.main()
