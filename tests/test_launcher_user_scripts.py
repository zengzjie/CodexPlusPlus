from codex_session_delete.launcher import CodexPlusRuntime, handle_bridge_request
from codex_session_delete.models import ExportResult, ExportStatus
from codex_session_delete.settings_store import SettingsStore
from codex_session_delete.user_scripts import UserScriptManager


class FakeDeleteService:
    def delete(self, session):
        raise AssertionError("delete should not be called")

    def undo(self, undo_token):
        raise AssertionError("undo should not be called")

    def find_archived_thread_by_title(self, title):
        return None


class FakeExportService:
    def export(self, session):
        return ExportResult(ExportStatus.EXPORTED, session.session_id, "Exported", filename="thread.md", markdown="# Thread\n")


class FakeRuntime:
    def __init__(self, manager):
        self.user_scripts = manager
        self.injected = []
        self.devtools_opened = False
        self.repaired = False

    def reload_user_scripts(self):
        bundle = self.user_scripts.build_enabled_bundle()
        self.injected.append(bundle)
        return self.user_scripts.inventory()

    def open_devtools(self):
        self.devtools_opened = True
        return {"status": "ok"}

    def backend_status(self):
        return {"status": "ok", "message": "本地服务已连接"}

    def repair_backend(self):
        self.repaired = True
        return {"status": "ok", "message": "本地服务已修复"}


def test_handle_bridge_request_lists_user_scripts(tmp_path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    (builtin / "demo.js").write_text("window.demo = true;", encoding="utf-8")
    manager = UserScriptManager(builtin, user, tmp_path / "config.json")
    runtime = FakeRuntime(manager)

    result = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/user-scripts/list", {}, runtime)

    assert result["enabled"] is True
    assert result["scripts"][0]["key"] == "builtin:demo.js"


def test_handle_bridge_request_updates_user_script_toggles(tmp_path):
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = FakeRuntime(manager)

    global_result = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/user-scripts/set-enabled", {"enabled": False}, runtime)
    script_result = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/user-scripts/set-script-enabled", {"key": "user:a.js", "enabled": False}, runtime)

    assert global_result["enabled"] is False
    assert script_result["scripts"] == []
    assert manager.load_config().scripts["user:a.js"] is False


def test_handle_bridge_request_reports_and_repairs_backend_status(tmp_path):
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = FakeRuntime(manager)

    status = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/backend/status", {}, runtime)
    repaired = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/backend/repair", {}, runtime)

    assert status == {"status": "ok", "message": "本地服务已连接"}
    assert runtime.repaired is True
    assert repaired == {"status": "ok", "message": "本地服务已修复"}


def test_handle_bridge_request_gets_backend_settings(monkeypatch, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.update({"providerSyncEnabled": True})
    monkeypatch.setattr("codex_session_delete.launcher.SettingsStore", lambda: store)
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = FakeRuntime(manager)

    result = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/settings/get", {}, runtime)

    assert result == {"providerSyncEnabled": True}


def test_handle_bridge_request_sets_backend_settings(monkeypatch, tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    monkeypatch.setattr("codex_session_delete.launcher.SettingsStore", lambda: store)
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = FakeRuntime(manager)

    result = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/settings/set", {"providerSyncEnabled": True}, runtime)

    assert result == {"providerSyncEnabled": True}
    assert store.load().provider_sync_enabled is True


def test_handle_bridge_request_exports_markdown(tmp_path):
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = FakeRuntime(manager)

    exported = handle_bridge_request(FakeDeleteService(), FakeExportService(), "/export-markdown", {"session_id": "s1", "title": "First"}, runtime)

    assert exported["status"] == "exported"
    assert exported["filename"] == "thread.md"


def test_runtime_backend_status_reports_failed_when_bridge_disconnected(tmp_path):
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = CodexPlusRuntime(None, manager, debug_port=9229, bridge_socket=type("Socket", (), {"connected": False})())

    status = runtime.backend_status()

    assert status == {"status": "failed", "message": "本地服务桥接已断开"}


def test_runtime_repair_backend_invokes_repair_callback_when_bridge_disconnected(tmp_path):
    manager = UserScriptManager(tmp_path / "builtin", tmp_path / "user", tmp_path / "config.json")
    runtime = CodexPlusRuntime(None, manager, debug_port=9229, bridge_socket=type("Socket", (), {"connected": False})())
    seen = []

    runtime.repair_callback = lambda: seen.append("repair") or {"status": "ok", "message": "本地服务已修复"}

    repaired = runtime.repair_backend()

    assert repaired == {"status": "ok", "message": "本地服务已修复"}
    assert seen == ["repair"]
