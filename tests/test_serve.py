"""The port guard.

Worth a test because the failure it prevents is silent: two servers bound to
one port, the older one answering, and a change appearing to do nothing.
"""

import socket

from app.serve import already_serving


def test_a_busy_port_is_detected():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        assert already_serving(*listener.getsockname())


def test_a_free_port_is_not():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert not already_serving("127.0.0.1", port)
