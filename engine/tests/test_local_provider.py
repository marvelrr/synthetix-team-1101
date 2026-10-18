import sys

import pytest

from engine import local_provider


class CommandCaptured(Exception):
    pass


def arguments(tmp_path, monkeypatch, extra=()):
    runtime = tmp_path / "fake-llama-server"
    model = tmp_path / "fake-model.gguf"
    runtime.touch()
    model.touch()
    monkeypatch.setattr(local_provider, "load_dotenv", lambda: None)
    monkeypatch.setattr(sys, "argv", ["engine.local_provider", "--runtime", str(runtime),
                                    "--model-file", str(model), "--port", "12340",
                                    "--alias", "fixture-local", *extra])
    return str(runtime)


@pytest.mark.parametrize("configured,requested,effective", [
    (None, None, "cpu"), ("metal", None, "metal"),
    ("metal", "cpu", "cpu"), ("cpu", "metal", "metal"),
])
def test_device_config_controls_real_runtime_command_without_launching(tmp_path, monkeypatch, capsys,
                                                                      configured, requested, effective):
    if configured is None:
        monkeypatch.delenv("SYNTHETIX_LOCAL_DEVICE", raising=False)
    else:
        monkeypatch.setenv("SYNTHETIX_LOCAL_DEVICE", configured)
    extra = ["--plain-json", *( ["--device", requested] if requested else [])]
    runtime = arguments(tmp_path, monkeypatch, extra)
    captured = []
    def execv(executable, command):
        captured.append((executable, command))
        raise CommandCaptured
    monkeypatch.setattr(local_provider.os, "execv", execv)
    with pytest.raises(CommandCaptured):
        local_provider.main()
    executable, command = captured[0]
    assert executable == runtime and command[0] == runtime
    value = lambda flag: command[command.index(flag) + 1]
    assert value("--port") == "12340" and value("--host") == "127.0.0.1"
    assert value("--alias") == "fixture-local" and value("--parallel") == "1"
    assert value("--ctx-size") == "8192"
    assert {"--offline", "--no-webui", "--log-disable"}.issubset(command)
    if effective == "metal":
        assert value("--device") == "MTL0" and value("--n-gpu-layers") == "all"
        assert value("--fit") == "on" and value("--flash-attn") == "auto"
        assert {"--kv-offload", "--op-offload"}.issubset(command)
        assert "--no-kv-offload" not in command and "--no-op-offload" not in command
    else:
        assert value("--device") == "none" and value("--n-gpu-layers") == "0"
        assert value("--fit") == "off"
        assert {"--no-kv-offload", "--no-op-offload"}.issubset(command)
        assert "--kv-offload" not in command and "--op-offload" not in command
    output = capsys.readouterr().out
    assert ("Metal" if effective == "metal" else "CPU") in output


def test_invalid_device_environment_fails_before_starting_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIX_LOCAL_DEVICE", "unsupported")
    arguments(tmp_path, monkeypatch, ["--plain-json"])
    monkeypatch.setattr(local_provider.os, "execv", lambda *args: pytest.fail("must not start runtime"))
    with pytest.raises(SystemExit) as error:
        local_provider.main()
    assert error.value.code == 2


def test_metal_schema_backend_uses_private_port_and_is_closed(tmp_path, monkeypatch):
    from engine import schema_provider
    arguments(tmp_path, monkeypatch, ["--device", "metal"])
    commands, terminated = [], []
    class Process:
        returncode = None
        def poll(self): return self.returncode
        def terminate(self):
            terminated.append(True)
            self.returncode = 0
        def wait(self, **kwargs): return self.returncode
    def popen(command, **kwargs):
        commands.append(command)
        assert kwargs["stdout"] == local_provider.subprocess.DEVNULL
        assert kwargs["stderr"] == local_provider.subprocess.DEVNULL
        return Process()
    class Health:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(local_provider.subprocess, "Popen", popen)
    monkeypatch.setattr(local_provider, "urlopen", lambda *args, **kwargs: Health())
    monkeypatch.setattr(local_provider.signal, "signal", lambda *args: None)
    def serve(upstream, port):
        assert upstream == "http://127.0.0.1:12341" and port == 12340
        raise KeyboardInterrupt
    monkeypatch.setattr(schema_provider, "serve_proxy", serve)
    local_provider.main()
    assert commands[0][commands[0].index("--port") + 1] == "12341"
    assert commands[0][commands[0].index("--device") + 1] == "MTL0"
    assert terminated == [True]
