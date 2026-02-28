import os
import sys


def _with_src_path():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def test_package_api_imports():
    _with_src_path()
    from vakdeepgram.api.main import app  # noqa: F401
    from vakdeepgram.api.chat import chat  # noqa: F401
    from vakdeepgram.api.websocket import websocket_endpoint  # noqa: F401
    from vakdeepgram.api.twilio import twilio_chat, twilio_websocket_endpoint  # noqa: F401


def test_package_services_imports():
    _with_src_path()
    from vakdeepgram.services import resolve_auth_for_connection  # noqa: F401
    from vakdeepgram.services import resolve_context_for_request  # noqa: F401


def test_package_provider_clients_imports():
    _with_src_path()
    from vakdeepgram.providers.clients import SetmoreApiClient  # noqa: F401
    from vakdeepgram.providers.clients import SquareApiClient  # noqa: F401
    from vakdeepgram.providers.clients import ensure_provider_access_context  # noqa: F401

