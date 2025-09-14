import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..services.integration_manager import get_integration_manager, IntegrationManagerError

logger = logging.getLogger(__name__)


def _load_json(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return json.loads(p.read_text(encoding="utf-8"))


async def _register(name: str, cfg_path: str) -> Dict[str, Any]:
    mgr = get_integration_manager()
    cfg = _load_json(cfg_path)
    cfg["name"] = name
    await mgr.register_integration(name, cfg)
    return cfg


async def _list() -> Dict[str, Dict[str, Any]]:
    mgr = get_integration_manager()
    return await mgr.list_integrations()


async def _get(name: str) -> Optional[Dict[str, Any]]:
    mgr = get_integration_manager()
    return await mgr.get_config(name)


async def _delete(name: str) -> bool:
    mgr = get_integration_manager()
    cfg = await mgr.get_config(name)
    if cfg is None:
        return False
    async with mgr._lock:
        mgr._cfg.pop(name, None)
    return True


# Quick test helpers that try to route to appropriate service
async def _test_email(name: str, to: str, subject: str, body: str) -> Dict[str, Any]:
    from ..integrations.email.email_service import get_email_service

    svc = get_email_service()
    # ensure integration config exists
    await svc.register_integration(name, svc._cfg.get(name) or {})
    # send a message (best-effort)
    return await svc.send_email(name, to=to, subject=subject, body_text=body)


async def _test_storage_list(name: str, path: Optional[str] = None) -> Dict[str, Any]:
    from ..integrations.storage.storage_service import get_storage_service

    svc = get_storage_service()
    return {"files": await svc.list_files(name, path=path or None)}


async def _test_messaging_send(name: str, channel: Optional[str], text: str) -> Dict[str, Any]:
    from ..integrations.messaging.notification_service import get_notification_service

    svc = get_notification_service()
    if channel:
        return {"result": await svc.send_via_messaging(name, channel=channel, text=text)}
    return {"result": await svc.send_via_messaging(name, channel=None, text=text)}


async def _test_calendar_list(name: str) -> Dict[str, Any]:
    from ..integrations.calendar.calendar_service import get_calendar_service

    svc = get_calendar_service()
    return {"events": await svc.list_events(name)}


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, default=str, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="integration_tool", description="Manage/test integrations")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register", help="Register integration from JSON file")
    p_reg.add_argument("name")
    p_reg.add_argument("config_path")

    p_list = sub.add_parser("list", help="List integrations")

    p_get = sub.add_parser("get", help="Get integration config")
    p_get.add_argument("name")

    p_del = sub.add_parser("delete", help="Delete integration")
    p_del.add_argument("name")

    p_test_email = sub.add_parser("test-email", help="Send a test email via integration")
    p_test_email.add_argument("name")
    p_test_email.add_argument("to")
    p_test_email.add_argument("--subject", default="Test message")
    p_test_email.add_argument("--body", default="This is a test")

    p_test_storage = sub.add_parser("test-storage-list", help="List files for storage integration")
    p_test_storage.add_argument("name")
    p_test_storage.add_argument("--path", default="/")

    p_test_msg = sub.add_parser("test-messaging", help="Send a test message via messaging integration")
    p_test_msg.add_argument("name")
    p_test_msg.add_argument("--channel", default=None)
    p_test_msg.add_argument("--text", default="Test message")

    p_test_cal = sub.add_parser("test-calendar-list", help="List calendar events for integration")
    p_test_cal.add_argument("name")

    args = parser.parse_args()

    try:
        if args.cmd == "register":
            res = asyncio.run(_register(args.name, args.config_path))
            _print_json({"registered": res})
        elif args.cmd == "list":
            res = asyncio.run(_list())
            _print_json(res)
        elif args.cmd == "get":
            res = asyncio.run(_get(args.name))
            if res is None:
                print(f"Integration not found: {args.name}")
            else:
                _print_json(res)
        elif args.cmd == "delete":
            ok = asyncio.run(_delete(args.name))
            _print_json({"deleted": ok, "name": args.name})
        elif args.cmd == "test-email":
            try:
                res = asyncio.run(_test_email(args.name, args.to, args.subject, args.body))
                _print_json(res)
            except Exception as e:
                print("email test failed:", str(e))
        elif args.cmd == "test-storage-list":
            try:
                res = asyncio.run(_test_storage_list(args.name, path=args.path))
                _print_json(res)
            except Exception as e:
                print("storage test failed:", str(e))
        elif args.cmd == "test-messaging":
            try:
                res = asyncio.run(_test_messaging_send(args.name, args.channel, args.text))
                _print_json(res)
            except Exception as e:
                print("messaging test failed:", str(e))
        elif args.cmd == "test-calendar-list":
            try:
                res = asyncio.run(_test_calendar_list(args.name))
                _print_json(res)
            except Exception as e:
                print("calendar test failed:", str(e))
    except IntegrationManagerError as exc:
        print("integration manager error:", str(exc))
    except Exception as exc:
        logger.exception("cli error")
        print("error:", str(exc))


if __name__ == "__main__":
    main()
