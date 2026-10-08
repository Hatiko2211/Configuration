import json
import tempfile
import unittest
from pathlib import Path

from src.shell import ShellError, VirtualShell


class VirtualShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.shell = VirtualShell(str(root / "vfs.json"), str(root / "users.json"),
                                  str(root / "initial.json"), username="student")

    def tearDown(self): self.tmp.cleanup()

    def test_prompt_has_login_host_and_path(self):
        prompt = self.shell.prompt()
        self.assertIn("student@", prompt); self.assertTrue(prompt.endswith("~$ "))

    def test_whoami(self): self.assertEqual(self.shell.execute("whoami"), "student")
    def test_pwd_initial_home(self): self.assertEqual(self.shell.execute("pwd"), "/home/student")
    def test_ls_home_lists_welcome(self): self.assertEqual(self.shell.execute("ls"), "welcome.txt")
    def test_ls_absolute_directory(self): self.assertEqual(self.shell.execute("ls /"), "etc  home  tmp")
    def test_cd_parent(self):
        self.shell.execute("cd ..")
        self.assertEqual(self.shell.execute("pwd"), "/home")
    def test_cd_absolute(self):
        self.shell.execute("cd /tmp")
        self.assertEqual(self.shell.cwd, "/tmp")
    def test_cd_rejects_file(self): self.assertIn("Not a directory", self.shell.execute("cd welcome.txt"))
    def test_cd_rejects_missing(self): self.assertIn("No such file", self.shell.execute("cd /missing"))
    def test_path_cannot_escape_root(self): self.assertEqual(self.shell.resolve("../../.."), "/")
    def test_unknown_command(self): self.assertIn("Command not found", self.shell.execute("not-a-command"))
    def test_help_lists_commands(self): self.assertIn("vfs-init", self.shell.execute("help"))
    def test_exit_stops_loop(self):
        self.shell.execute("exit")
        self.assertFalse(self.shell.running)
    def test_state_is_persisted(self):
        self.shell.execute("cd /tmp")
        with open(self.shell.storage, encoding="utf-8") as f: self.assertEqual(json.load(f)["type"], "dir")
    def test_vfs_init_restores_snapshot(self):
        self.shell.fs["children"]["tmp"]["children"]["junk"] = {"type": "file", "owner": "student", "content": "x"}
        self.shell.execute("vfs-init")
        self.assertNotIn("junk", self.shell.node("/tmp")["children"])
    def test_chown_requires_root(self): self.assertIn("requires root", self.shell.execute("chown root /tmp"))
    def test_chown_unknown_user(self):
        admin = VirtualShell(self.shell.storage, self.shell.user_db, self.shell.initial_fs, username="root")
        self.assertIn("Unknown user", admin.execute("chown nobody /tmp"))
    def test_root_can_change_owner(self):
        admin = VirtualShell(self.shell.storage, self.shell.user_db, self.shell.initial_fs, username="root")
        self.assertEqual(admin.execute("chown student /tmp"), "")
        self.assertEqual(admin.node("/tmp")["owner"], "student")
    def test_useradd_requires_root(self): self.assertIn("requires root", self.shell.execute("useradd guest pass"))
    def test_root_can_add_user_and_home(self):
        admin = VirtualShell(self.shell.storage, self.shell.user_db, self.shell.initial_fs, username="root")
        self.assertEqual(admin.execute("useradd guest pass"), "User guest created.")
        self.assertEqual(admin.node("/home/guest")["owner"], "guest")
    def test_useradd_rejects_duplicate(self):
        admin = VirtualShell(self.shell.storage, self.shell.user_db, self.shell.initial_fs, username="root")
        self.assertIn("already exists", admin.execute("useradd student newpass"))
    def test_quoted_arguments_are_parsed(self):
        self.assertEqual(self.shell.execute('ls "/home/student"'), "welcome.txt")


if __name__ == "__main__": unittest.main()
