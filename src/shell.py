"""A small UNIX-like shell backed by a persistent virtual file system."""
from __future__ import annotations

import json
import shlex
import getpass
import socket
from pathlib import PurePosixPath
from typing import Any


class ShellError(Exception):
    """An expected command or virtual file system error."""


def default_fs() -> dict[str, Any]:
    return {
        "type": "dir", "owner": "root", "children": {
            "home": {"type": "dir", "owner": "root", "children": {
                "student": {"type": "dir", "owner": "student", "children": {
                    "welcome.txt": {"type": "file", "owner": "student", "content": "Welcome to Variant 11!\n"}
                }}
            }},
            "tmp": {"type": "dir", "owner": "root", "children": {}},
            "etc": {"type": "dir", "owner": "root", "children": {
                "motd": {"type": "file", "owner": "root", "content": "Virtual UNIX shell\n"}
            }}
        }
    }


class VirtualShell:
    """Command interpreter with users, paths, persistence, and ownership."""

    def __init__(self, storage: str = "data/vfs.json", user_db: str = "data/users.json",
                 initial_fs: str = "data/initial_vfs.json", username: str | None = None):
        self.storage, self.user_db, self.initial_fs = storage, user_db, initial_fs
        self.username = username or getpass.getuser()
        self.cwd = "/home/student" if self.username == "student" else "/"
        self.users = self._load_users()
        self.fs = self._load_fs()
        self.running = True

    def _load_users(self) -> dict[str, dict[str, str]]:
        try:
            with open(self.user_db, encoding="utf-8") as f:
                users = json.load(f)
            if not isinstance(users, dict) or not users:
                raise ValueError("user database must be a non-empty object")
            return users
        except FileNotFoundError:
            users = {"root": {"password": "root", "home": "/"},
                     "student": {"password": "student", "home": "/home/student"}}
            self._save_json(self.user_db, users)
            return users

    def _load_fs(self) -> dict[str, Any]:
        try:
            with open(self.storage, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            fs = default_fs()
            self._save_json(self.storage, fs)
            self._save_json(self.initial_fs, fs)
            return fs

    @staticmethod
    def _save_json(path: str, value: Any) -> None:
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        temp = path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)

    def save(self) -> None:
        self._save_json(self.storage, self.fs)

    def resolve(self, path: str) -> str:
        if not path or path == ".":
            path = self.cwd
        elif not path.startswith("/"):
            path = str(PurePosixPath(self.cwd) / path)
        parts: list[str] = []
        for part in path.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts: parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def node(self, path: str) -> dict[str, Any]:
        node = self.fs
        resolved = self.resolve(path)
        for part in resolved.strip("/").split("/") if resolved != "/" else []:
            if node.get("type") != "dir" or part not in node.get("children", {}):
                raise ShellError(f"No such file or directory: {path}")
            node = node["children"][part]
        return node

    def _parent(self, path: str) -> tuple[dict[str, Any], str]:
        resolved = self.resolve(path)
        if resolved == "/": raise ShellError("Cannot modify the root directory")
        parent_path, name = str(PurePosixPath(resolved).parent), PurePosixPath(resolved).name
        parent = self.node(parent_path)
        if parent.get("type") != "dir": raise ShellError("Parent is not a directory")
        return parent, name

    def _require_owner(self, node: dict[str, Any]) -> None:
        if self.username != "root" and node.get("owner") != self.username:
            raise ShellError("Permission denied (only root or the owner may change ownership)")

    def prompt(self) -> str:
        short = "~" if self.cwd == self.users.get(self.username, {}).get("home") else self.cwd
        return f"{self.username}@{socket.gethostname()}:{short}$ "

    def execute(self, line: str) -> str:
        try:
            args = shlex.split(line)
            if not args: return ""
            command, *argv = args
            result = self._dispatch(command, argv)
            self.save()
            return result
        except (ShellError, json.JSONDecodeError, OSError) as exc:
            return f"{exc}"

    def _dispatch(self, cmd: str, a: list[str]) -> str:
        if cmd == "exit": self.running = False; return ""
        if cmd == "help": return "Commands: help, ls [path], cd [path], pwd, whoami, useradd USER PASSWORD, chown USER PATH, vfs-init, exit"
        if cmd == "whoami": return self.username
        if cmd == "pwd": return self.cwd
        if cmd == "ls":
            path = a[0] if a else self.cwd
            n = self.node(path)
            if n["type"] == "file": return PurePosixPath(self.resolve(path)).name
            return "  ".join(sorted(n.get("children", {})))
        if cmd == "cd":
            target = a[0] if a else self.users.get(self.username, {}).get("home", "/")
            n = self.node(target)
            if n["type"] != "dir": raise ShellError(f"Not a directory: {target}")
            self.cwd = self.resolve(target)
            return ""
        if cmd == "chown":
            if len(a) != 2: raise ShellError("Usage: chown USER PATH")
            if self.username != "root": raise ShellError("Permission denied: chown requires root")
            user, path = a
            if user not in self.users: raise ShellError(f"Unknown user: {user}")
            n = self.node(path); n["owner"] = user
            return ""
        if cmd == "useradd":
            if len(a) != 2: raise ShellError("Usage: useradd USER PASSWORD")
            if self.username != "root": raise ShellError("Permission denied: useradd requires root")
            user, password = a
            if user in self.users: raise ShellError(f"User already exists: {user}")
            if not user.isidentifier(): raise ShellError("Username must contain only letters, digits, and underscores")
            home = f"/home/{user}"
            self.users[user] = {"password": password, "home": home}
            try:
                home_node = self.node("/home")
            except ShellError:
                self.fs["children"]["home"] = {"type": "dir", "owner": "root", "children": {}}
                home_node = self.node("/home")
            home_node["children"][user] = {"type": "dir", "owner": user, "children": {}}
            self._save_json(self.user_db, self.users)
            return f"User {user} created."
        if cmd == "vfs-init":
            try:
                with open(self.initial_fs, encoding="utf-8") as f: self.fs = json.load(f)
            except FileNotFoundError:
                self.fs = default_fs(); self._save_json(self.initial_fs, self.fs)
            self.cwd = self.users.get(self.username, {}).get("home", "/")
            return "VFS restored to its initial state."
        raise ShellError(f"Command not found: {cmd}. Type 'help' for available commands.")

    def login(self) -> bool:
        print("Virtual UNIX shell. Type 'exit' to quit.")
        for _ in range(3):
            name = input("login: ").strip()
            password = getpass.getpass("Password: ")
            record = self.users.get(name)
            if record and record.get("password") == password:
                self.username = name
                self.cwd = record.get("home", "/")
                return True
            print("Login incorrect")
        print("Too many failed attempts.")
        return False

    def run(self, authenticate: bool = True) -> None:
        if authenticate and not self.login(): return
        while self.running:
            try: line = input(self.prompt())
            except (EOFError, KeyboardInterrupt):
                print(); break
            output = self.execute(line)
            if output: print(output)


if __name__ == "__main__":
    VirtualShell().run()
