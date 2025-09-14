import argparse
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Union

from ..integrations.email.email_service import get_email_service, EmailServiceError

logger = logging.getLogger(__name__)


async def send_test_email(
    integration_name: str,
    to: Union[str, List[str]],
    subject: str,
    body_text: str,
    html: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send a simple test email using a registered email integration.
    Returns the provider response dict on success.
    """
    svc = get_email_service()
    # Ensure integration registered (no-op if present)
    try:
        await svc.register_integration(
            integration_name, svc._cfg.get(integration_name) or {}
        )
    except Exception:
        # best-effort; ignore registration errors here
        logger.debug(
            "send_test_email: ensure registration failed/ignored for %s",
            integration_name,
            exc_info=True,
        )
    return await svc.send_email(
        integration_name, to=to, subject=subject, body_text=body_text, html=html
    )


async def list_messages(
    integration_name: str, query: Optional[str] = None, max_results: int = 50
) -> List[Dict[str, Any]]:
    """
    List recent messages for the given email integration.
    """
    svc = get_email_service()
    return await svc.list_messages(
        integration_name, query=query, max_results=max_results
    )


async def get_message(
    integration_name: str, message_id: str, format: str = "full"
) -> Optional[Dict[str, Any]]:
    """
    Fetch a single message by id from the named integration.
    """
    svc = get_email_service()
    return await svc.get_message(integration_name, message_id, format=format)


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, default=str, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="email_tools", description="Email integration helpers"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="Send a test email")
    p_send.add_argument("integration")
    p_send.add_argument("to")
    p_send.add_argument("--subject", default="Test message")
    p_send.add_argument("--body", default="This is a test")
    p_send.add_argument("--html", default=None)

    p_list = sub.add_parser("list", help="List messages")
    p_list.add_argument("integration")
    p_list.add_argument("--query", default=None)
    p_list.add_argument("--max", type=int, default=50)

    p_get = sub.add_parser("get", help="Get a message by id")
    p_get.add_argument("integration")
    p_get.add_argument("message_id")
    p_get.add_argument("--format", default="full")

    args = parser.parse_args()

    try:
        if args.cmd == "send":
            try:
                res = asyncio.run(
                    send_test_email(
                        args.integration,
                        args.to,
                        args.subject,
                        args.body,
                        html=args.html,
                    )
                )
                _print_json(res)
            except EmailServiceError as e:
                print("send failed:", str(e))
        elif args.cmd == "list":
            try:
                res = asyncio.run(
                    list_messages(
                        args.integration, query=args.query, max_results=args.max
                    )
                )
                _print_json(res)
            except EmailServiceError as e:
                print("list failed:", str(e))
        elif args.cmd == "get":
            try:
                res = asyncio.run(
                    get_message(args.integration, args.message_id, format=args.format)
                )
                _print_json(res)
            except EmailServiceError as e:
                print("get failed:", str(e))
    except Exception as exc:
        logger.exception("email_tools error")
        print("error:", str(exc))


if __name__ == "__main__":
    main()
