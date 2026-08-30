import os
import tempfile
import unittest

from stdedit.explorer import PARENT, FileExplorer


class ExplorerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        # Layout:
        #   root/
        #     alpha.txt
        #     beta.py
        #     sub_one/  (contains inner.txt)
        #     sub_two/
        #     .hidden_dir/  (contains secret.txt)
        #     .hidden_file
        os.mkdir(os.path.join(self.root, "sub_one"))
        os.mkdir(os.path.join(self.root, "sub_two"))
        os.mkdir(os.path.join(self.root, ".hidden_dir"))
        with open(os.path.join(self.root, "alpha.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(self.root, "beta.py"), "w") as f:
            f.write("b")
        with open(os.path.join(self.root, ".hidden_file"), "w") as f:
            f.write("h")
        with open(os.path.join(self.root, "sub_one", "inner.txt"), "w") as f:
            f.write("i")
        with open(os.path.join(self.root, ".hidden_dir", "secret.txt"), "w") as f:
            f.write("s")

    def tearDown(self):
        self._tmp.cleanup()

    def paths(self, explorer):
        return [item[2] for item in explorer.items]


class TestTreeBuilding(ExplorerTestBase):
    def test_tree_visible_and_focused_by_default(self):
        e = FileExplorer(self.root)
        self.assertTrue(e.visible)
        self.assertTrue(e.active)

    def test_dirs_listed_before_files_sorted_case_insensitive(self):
        e = FileExplorer(self.root)
        names = [os.path.basename(p) for p in self.paths(e) if p != PARENT]
        dirs = names[:2]
        files = names[2:]
        self.assertEqual(sorted(dirs, key=str.lower), ["sub_one", "sub_two"])
        self.assertEqual(files, ["alpha.txt", "beta.py"])

    def test_hidden_entries_filtered_by_default(self):
        e = FileExplorer(self.root)
        all_paths = " ".join(self.paths(e))
        self.assertNotIn(".hidden_file", all_paths)
        self.assertNotIn(".hidden_dir", all_paths)

    def test_toggle_hidden_reveals_dotfiles(self):
        e = FileExplorer(self.root)
        e.toggle_hidden()
        all_paths = " ".join(self.paths(e))
        self.assertIn(".hidden_file", all_paths)
        self.assertIn(".hidden_dir", all_paths)
        # And back off again.
        e.toggle_hidden()
        self.assertNotIn(".hidden_file", " ".join(self.paths(e)))

    def test_ignored_names_never_shown(self):
        junk = os.path.join(self.root, "__pycache__")
        venv = os.path.join(self.root, ".venv")
        node = os.path.join(self.root, "node_modules")
        for d in (junk, venv, node):
            os.mkdir(d)
            with open(os.path.join(d, "x.bin"), "w") as f:
                f.write("x")
        e = FileExplorer(self.root)
        e.toggle_hidden()  # even with hidden files visible
        joined = " ".join(self.paths(e))
        for d in (junk, venv, node):
            self.assertNotIn(os.path.basename(d), joined)


class TestJunkFiltering(ExplorerTestBase):
    def make_junk(self):
        """Create representative IDE/build artifacts in the temp root."""
        os.mkdir(os.path.join(self.root, ".idea"))
        os.mkdir(os.path.join(self.root, ".vscode"))
        os.mkdir(os.path.join(self.root, ".git"))
        os.mkdir(os.path.join(self.root, "dist"))
        os.mkdir(os.path.join(self.root, "build"))
        os.mkdir(os.path.join(self.root, "env"))
        os.mkdir(os.path.join(self.root, "mypkg.egg-info"))
        with open(os.path.join(self.root, "module.pyc"), "w") as f:
            f.write("junk")

    def test_ide_and_build_artifacts_hidden_by_default(self):
        self.make_junk()
        e = FileExplorer(self.root)
        joined = " ".join(self.paths(e))
        for junk in (".idea", ".vscode", ".git", "dist", "build", "env",
                     "mypkg.egg-info", "module.pyc"):
            self.assertNotIn(junk, joined)

    def test_ide_and_build_artifacts_stay_hidden_with_h(self):
        self.make_junk()
        e = FileExplorer(self.root)
        e.toggle_hidden()
        joined = " ".join(self.paths(e))
        for junk in (".idea", ".vscode", ".git", "dist", "build", "env",
                     "mypkg.egg-info", "module.pyc"):
            self.assertNotIn(junk, joined)

    def test_useful_dotfiles_still_toggle_with_h(self):
        self.make_junk()
        with open(os.path.join(self.root, ".gitignore"), "w") as f:
            f.write("*.log\n")
        e = FileExplorer(self.root)
        self.assertNotIn(".gitignore", " ".join(self.paths(e)))
        e.toggle_hidden()
        self.assertIn(".gitignore", " ".join(self.paths(e)))

    def test_project_files_unaffected_by_filtering(self):
        self.make_junk()
        e = FileExplorer(self.root)
        joined = " ".join(self.paths(e))
        for keep in ("alpha.txt", "beta.py", "sub_one", "sub_two"):
            self.assertIn(keep, joined)


class TestRootingAndNavigation(ExplorerTestBase):
    def test_set_root_reroots_tree(self):
        e = FileExplorer(".")
        e.set_root(self.root)
        self.assertEqual(e.root_dir, os.path.abspath(self.root))
        self.assertIn("alpha.txt", " ".join(e.items[i][1] for i in range(len(e.items))))

    def test_set_root_ignores_non_directories(self):
        e = FileExplorer(self.root)
        before = list(e.items)
        e.set_root(os.path.join(self.root, "alpha.txt"))  # a file
        self.assertEqual(e.items, before)

    def test_parent_entry_present_with_parent(self):
        e = FileExplorer(self.root)  # root has a parent on any normal FS
        self.assertEqual(e.items[0], (0, PARENT, PARENT, False))

    def test_no_parent_entry_at_filesystem_root(self):
        e = FileExplorer("/")
        e.refresh()
        self.assertTrue(all(item[2] != PARENT for item in e.items))

    def test_go_up_selects_previous_root(self):
        sub_one = os.path.join(self.root, "sub_one")
        e = FileExplorer(sub_one)
        self.assertTrue(e.can_go_up())
        e.go_up()
        self.assertEqual(e.root_dir, os.path.abspath(self.root))
        selected = e.get_selected()
        self.assertIsNotNone(selected)
        self.assertTrue(selected[3])  # is_dir
        self.assertEqual(selected[2], os.path.abspath(sub_one))

    def test_expansion_state_survives_climb_and_return(self):
        sub_one = os.path.join(self.root, "sub_one")
        e = FileExplorer(self.root)
        # Expand sub_one by toggling its entry.
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.toggle_expand(idx)
        self.assertIn("inner.txt", " ".join(it[1] for it in e.items))
        e.go_up()
        e.set_root(self.root)
        self.assertIn(
            "sub_one", " ".join(it[1] for it in e.items if it[3])
        )
        # Still expanded after returning: inner.txt is listed again.
        self.assertIn("inner.txt", " ".join(it[1] for it in e.items))


class TestCreation(ExplorerTestBase):
    def test_selected_directory_matrix(self):
        e = FileExplorer(self.root)
        # Nothing meaningful selected -> root. (<..> is selected at index 0.)
        self.assertEqual(e.selected_directory(), os.path.abspath(self.root))
        e.selected_idx = 0  # <..> entry
        self.assertEqual(e.selected_directory(), os.path.abspath(self.root))
        # Directory selected -> inside it.
        sub_one = os.path.join(self.root, "sub_one")
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.selected_idx = idx
        self.assertEqual(e.selected_directory(), os.path.abspath(sub_one))
        # File selected -> its containing folder.
        alpha = os.path.join(self.root, "alpha.txt")
        idx = [i for i, it in enumerate(e.items) if it[2] == alpha][0]
        e.selected_idx = idx
        self.assertEqual(e.selected_directory(), os.path.abspath(self.root))

    def test_create_file_creates_selects_and_expands(self):
        e = FileExplorer(self.root)
        path, error = e.create_file("newmod.py")
        self.assertIsNone(error)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), 0)
        self.assertEqual(e.get_selected()[2], os.path.abspath(path))

    def test_create_file_inside_selected_folder(self):
        e = FileExplorer(self.root)
        sub_one = os.path.join(self.root, "sub_one")
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.selected_idx = idx
        path, error = e.create_file("deep.txt")
        self.assertIsNone(error)
        self.assertEqual(path, os.path.join(sub_one, "deep.txt"))

    def test_create_file_duplicate_rejected(self):
        e = FileExplorer(self.root)
        _, first_error = e.create_file("dup.txt")
        self.assertIsNone(first_error)
        _, error = e.create_file("dup.txt")
        self.assertIn("already exists", error)

    def test_create_file_invalid_names_rejected(self):
        e = FileExplorer(self.root)
        for bad in ("", "   ", "a/b", "..", ".", "x/y/z"):
            _, error = e.create_file(bad)
            self.assertIsNotNone(error, f"expected rejection for {bad!r}")

    def test_create_folder_creates_expands_and_selects(self):
        e = FileExplorer(self.root)
        path, error = e.create_folder("newdir")
        self.assertIsNone(error)
        self.assertTrue(os.path.isdir(path))
        # Selected on the new folder and expanded: creating inside works.
        self.assertEqual(e.get_selected()[2], os.path.abspath(path))
        inner_path, inner_error = e.create_file("inner.md")
        self.assertIsNone(inner_error)
        self.assertEqual(
            inner_path, os.path.join(path, "inner.md"),
            "new folder should be the creation target after being selected",
        )

    def test_create_folder_duplicate_rejected(self):
        e = FileExplorer(self.root)
        _, first_error = e.create_folder("twice")
        self.assertIsNone(first_error)
        # Move selection off the new folder so the target is the root again.
        alpha = os.path.join(self.root, "alpha.txt")
        e._select_path(alpha)
        _, error = e.create_folder("twice")
        self.assertIn("already exists", error)


class TestSelection(ExplorerTestBase):
    def test_move_selection_clamps_to_bounds(self):
        e = FileExplorer(self.root)
        count = len(e.items)
        e.move_selection(-5)
        self.assertEqual(e.selected_idx, 0)
        e.move_selection(count + 10)
        self.assertEqual(e.selected_idx, count - 1)

    def test_get_selected_out_of_range_returns_none(self):
        e = FileExplorer(self.root)
        e.selected_idx = len(e.items)
        self.assertIsNone(e.get_selected())

    def test_toggle_expand_adds_and_removes_children(self):
        sub_one = os.path.join(self.root, "sub_one")
        e = FileExplorer(self.root)
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.toggle_expand(idx)
        self.assertIn("inner.txt", " ".join(it[1] for it in e.items))
        idx = [i for i, it in enumerate(e.items) if it[2] == os.path.abspath(sub_one)][0]
        e.toggle_expand(idx)
        self.assertNotIn("inner.txt", " ".join(it[1] for it in e.items))

    def test_toggle_expand_ignores_files(self):
        alpha = os.path.join(self.root, "alpha.txt")
        e = FileExplorer(self.root)
        before = list(e.items)
        idx = [i for i, it in enumerate(e.items) if it[2] == alpha][0]
        e.toggle_expand(idx)
        self.assertEqual(e.items, before)


class TestSearch(ExplorerTestBase):
    def test_enter_exit_search(self):
        e = FileExplorer(self.root)
        e.enter_search()
        self.assertTrue(e.searching)
        self.assertEqual(e.search_query, "")
        self.assertEqual(e.search_results, [])
        e.exit_search()
        self.assertFalse(e.searching)
        self.assertEqual(e.search_query, "")

    def test_search_finds_files(self):
        e = FileExplorer(self.root)
        e.search("alpha")
        self.assertEqual(len(e.search_results), 1)
        self.assertEqual(e.search_results[0][2],
                         os.path.join(self.root, "alpha.txt"))

    def test_search_finds_dirs(self):
        e = FileExplorer(self.root)
        e.search("sub_one")
        self.assertEqual(len(e.search_results), 1)
        self.assertTrue(e.search_results[0][3])  # is_dir

    def test_search_case_insensitive(self):
        e = FileExplorer(self.root)
        e.search("ALPHA")
        self.assertEqual(len(e.search_results), 1)

    def test_search_finds_nested_files(self):
        e = FileExplorer(self.root)
        e.search("inner")
        self.assertEqual(len(e.search_results), 1)
        self.assertEqual(e.search_results[0][2],
                         os.path.join(self.root, "sub_one", "inner.txt"))

    def test_search_empty_query_returns_nothing(self):
        e = FileExplorer(self.root)
        e.search("")
        self.assertEqual(e.search_results, [])

    def test_search_respects_hidden_filter(self):
        e = FileExplorer(self.root)
        e.search("secret")
        self.assertEqual(len(e.search_results), 0)  # hidden by default
        e.show_hidden = True
        e.search("secret")
        self.assertEqual(len(e.search_results), 1)

    def test_search_respects_always_ignored(self):
        os.mkdir(os.path.join(self.root, "__pycache__"))
        with open(os.path.join(self.root, "__pycache__", "mod.pyc"), "w") as f:
            f.write("")
        e = FileExplorer(self.root)
        e.search("mod")
        self.assertEqual(len(e.search_results), 0)

    def test_search_no_results(self):
        e = FileExplorer(self.root)
        e.search("zzzznonexistent")
        self.assertEqual(e.search_results, [])
        self.assertEqual(e.selected_idx, 0)

    def test_search_results_are_flat(self):
        e = FileExplorer(self.root)
        e.search(".txt")
        for item in e.search_results:
            self.assertEqual(item[0], 0)  # all depth=0

    def test_navigate_search_results(self):
        e = FileExplorer(self.root)
        e.search("txt")
        e.move_selection(1)
        self.assertEqual(e.selected_idx, 1)
        e.move_selection(-1)
        self.assertEqual(e.selected_idx, 0)

    def test_search_excludes_parent_entry(self):
        e = FileExplorer(self.root)
        e.search("..")
        self.assertEqual(len(e.search_results), 0)

    def test_search_preserves_normal_tree_after_exit(self):
        e = FileExplorer(self.root)
        before = list(e.items)
        e.enter_search()
        e.search("alpha")
        e.exit_search()
        self.assertEqual(e.items, before)


class TestFileOperations(ExplorerTestBase):
    def select(self, explorer, path):
        explorer.selected_idx = next(
            i for i, item in enumerate(explorer.items)
            if os.path.abspath(item[2]) == os.path.abspath(path))

    def select_parent(self, explorer):
        explorer.selected_idx = next(
            i for i, item in enumerate(explorer.items) if item[2] == PARENT)

    def test_delete_file(self):
        e = FileExplorer(self.root)
        target = os.path.join(self.root, "alpha.txt")
        self.select(e, target)
        ok, msg = e.delete_selected()
        self.assertTrue(ok)
        self.assertEqual(msg, "Deleted alpha.txt")
        self.assertFalse(os.path.exists(target))

    def test_delete_directory_recursively(self):
        e = FileExplorer(self.root)
        target = os.path.join(self.root, "sub_one")
        self.select(e, target)
        ok, _ = e.delete_selected()
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(target))

    def test_delete_refuses_parent_entry(self):
        e = FileExplorer(self.root)
        self.select_parent(e)
        ok, msg = e.delete_selected()
        self.assertFalse(ok)
        self.assertEqual(msg, "Cannot delete parent entry")
        self.assertTrue(os.path.isdir(self.root))

    def test_delete_without_selection(self):
        e = FileExplorer(self.root)
        e.selected_idx = len(e.items) + 5   # out of range → no item
        ok, msg = e.delete_selected()
        self.assertFalse(ok)
        self.assertEqual(msg, "No item selected")

    def test_delete_missing_file_reports_failure(self):
        e = FileExplorer(self.root)
        target = os.path.join(self.root, "alpha.txt")
        self.select(e, target)
        os.remove(target)  # vanishes between listing and the delete action
        ok, msg = e.delete_selected()
        self.assertFalse(ok)
        self.assertIn("Delete failed", msg)

    def test_rename_file(self):
        e = FileExplorer(self.root)
        old = os.path.join(self.root, "beta.py")
        new = os.path.join(self.root, "gamma.py")
        self.select(e, old)
        ok, msg = e.rename_selected("gamma.py")
        self.assertTrue(ok)
        self.assertEqual(msg, "Renamed to gamma.py")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(new))
        self.assertEqual(e.get_selected()[2], new)

    def test_rename_rejects_existing_target(self):
        e = FileExplorer(self.root)
        self.select(e, os.path.join(self.root, "alpha.txt"))
        ok, msg = e.rename_selected("beta.py")
        self.assertFalse(ok)
        self.assertIn("already exists", msg)

    def test_rename_rejects_invalid_name(self):
        e = FileExplorer(self.root)
        self.select(e, os.path.join(self.root, "alpha.txt"))
        ok, msg = e.rename_selected("bad/name")
        self.assertFalse(ok)
        self.assertIn("single path component", msg)
        self.assertTrue(os.path.exists(os.path.join(self.root, "alpha.txt")))

    def test_rename_refuses_parent_entry(self):
        e = FileExplorer(self.root)
        self.select_parent(e)
        ok, msg = e.rename_selected("newname")
        self.assertFalse(ok)
        self.assertEqual(msg, "Cannot rename parent entry")

    def test_rename_directory(self):
        e = FileExplorer(self.root)
        old = os.path.join(self.root, "sub_two")
        new = os.path.join(self.root, "renamed_dir")
        self.select(e, old)
        ok, _ = e.rename_selected("renamed_dir")
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(new))

    def test_copy_path_absolute(self):
        e = FileExplorer(self.root)
        self.select(e, os.path.join(self.root, "beta.py"))
        self.assertEqual(e.copy_path(), os.path.join(self.root, "beta.py"))

    def test_copy_path_empty_without_selection(self):
        e = FileExplorer(self.root)
        e.selected_idx = len(e.items) + 5
        self.assertEqual(e.copy_path(), "")

    def test_copy_path_empty_for_parent(self):
        e = FileExplorer(self.root)
        self.select_parent(e)
        self.assertEqual(e.copy_path(), "")

    def test_copy_relative_path(self):
        e = FileExplorer(self.root)
        self.select(e, os.path.join(self.root, "beta.py"))
        self.assertEqual(e.copy_relative_path(), "beta.py")
        self.select(e, os.path.join(self.root, "sub_one"))
        self.assertEqual(e.copy_relative_path(), "sub_one")

    def test_copy_relative_path_empty_for_parent(self):
        e = FileExplorer(self.root)
        self.select_parent(e)
        self.assertEqual(e.copy_relative_path(), "")


class TestReveal(ExplorerTestBase):
    def selected_path_of(self, e):
        selected = e.get_selected()
        self.assertIsNotNone(selected)
        return selected[2]

    def test_reveal_top_level_file(self):
        e = FileExplorer(self.root)
        e.reveal(os.path.join(self.root, "beta.py"))
        self.assertEqual(self.selected_path_of(e), os.path.join(self.root, "beta.py"))

    def test_reveal_nested_file_expands_ancestors(self):
        e = FileExplorer(self.root)
        target = os.path.join(self.root, "sub_one", "inner.txt")
        e.reveal(target)
        self.assertIn(os.path.join(self.root, "sub_one"), e.expanded_dirs)
        self.assertEqual(self.selected_path_of(e), target)

    def test_reveal_directory_selects_it(self):
        e = FileExplorer(self.root)
        target = os.path.join(self.root, "sub_two")
        e.reveal(target)
        self.assertEqual(self.selected_path_of(e), target)

    def test_reveal_missing_path_is_safe(self):
        e = FileExplorer(self.root)
        before = e.selected_idx
        e.reveal(os.path.join(self.root, "nope.txt"))
        self.assertEqual(e.selected_idx, before)
        self.assertNotEqual(self.selected_path_of(e), os.path.join(self.root, "nope.txt"))

    def test_reveal_exits_search_mode(self):
        e = FileExplorer(self.root)
        e.enter_search()
        e.search("alpha")
        self.assertTrue(e.searching)
        target = os.path.join(self.root, "beta.py")
        e.reveal(target)
        self.assertFalse(e.searching)
        self.assertEqual(self.selected_path_of(e), target)


if __name__ == "__main__":
    unittest.main()
