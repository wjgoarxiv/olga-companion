from __future__ import annotations


class _CompletedProcess:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.returncode = 0
        kwargs["stdout"].write(b'{"status":"cancelled"}')

    def communicate(self, timeout=None):
        return (None, None)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9
