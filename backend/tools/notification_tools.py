import argparse
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Union

from ..integrations.messaging.notification_service import (
    get_notification_service,
    NotificationServiceError,
)

logger = logging.getLogger(__name__)


async def notify(
    integration_name: Optional[str] = None,
    channels: Optional[List[str]] = None,
    text: str = "",
    subject: Optional[str] = None,
    user_id: Optional[str] = None,
    email_to: Optional[Union[str, List[str]]] = None,
) -> Dict[str, Any]:
    """
    High-level notify: chooses messaging or email depending on args and integration config.
    Returns summary dict {"results": [...], "errors": [...]}
    """
    svc = get_notification_service()
    return await svc.notify(
        integration_name=integration_name,
        channels=channels,
        text=text,
        subject=subject,
        user_id=user_id,
        email_to=email_to,
    )


async def send_message(
    integration_name: str,
    channel: Optional[str],
    text: str,
    subject: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    svc = get_notification_service()
    return await svc.send_via_messaging(
        integration_name=integration_name, channel=channel, text=text, subject=subject, user_id=user_id
    )


async def broadcast(
    integration_name: str, channels: List[str], text: str, subject: Optional[str] = None
) -> List[Dict[str, Any]]:
    svc = get_notification_service()
    return await svc.broadcast(integration_name=integration_name, channels=channels, text=text, subject=subject)


async def send_email(
    integration_name: str,
    to: Union[str, List[str]],
    subject: str,
    body_text: str,
    html: Optional[str] = None,
) -> Dict[str, Any]:
    svc = get_notification_service()
    return await svc.send_via_email(integration_name=integration_name, to=to, subject=subject, body_text=body_text, html=html)


def list_integrations() -> Dict[str, Dict[str, Any]]:
    svc = get_notification_service()
    # expose copy of registered messaging/email integrations
    return dict(svc._cfg)


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, default=str, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="notification_tools", description="Notification integration helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_notify = sub.add_parser("notify", help="High-level notify (messaging or email)")
    p_notify.add_argument("--integration", default=None)
    p_notify.add_argument("--channels", nargs="*", default=[])
    p_notify.add_argument("--text", required=True)
    p_notify.add_argument("--subject", default=None)
    p_notify.add_argument("--user-id", default=None)
    p_notify.add_argument("--email-to", default=None)

    p_send = sub.add_parser("send-msg", help="Send a message via messaging integration")
    p_send.add_argument("integration")
    p_send.add_argument("--channel", default=None)
    p_send.add_argument("--text", required=True)
    p_send.add_argument("--subject", default=None)
    p_send.add_argument("--user-id", default=None)

    p_broadcast = sub.add_parser("broadcast", help="Broadcast message to multiple channels")
    p_broadcast.add_argument("integration")
    p_broadcast.add_argument("channels", nargs="+")
    p_broadcast.add_argument("--text", required=True)
    p_broadcast.add_argument("--subject", default=None)

    p_email = sub.add_parser("send-email", help="Send an email via integration")
    p_email.add_argument("integration")
    p_email.add_argument("to")
    p_email.add_argument("--subject", required=True)
    p_email.add_argument("--body", required=True)
    p_email.add_argument("--html", default=None)

    p_list = sub.add_parser("list", help="List registered notification integrations")

    args = parser.parse_args()

    try:
        if args.cmd == "notify":
            res = asyncio.run(
                notify(
                    integration_name=args.integration,
                    channels=args.channels or None,
                    text=args.text,
                    subject=args.subject,
                    user_id=args.user_id,
                    email_to=args.email_to,
                )
            )
            _print_json(res)
        elif args.cmd == "send-msg":
            res = asyncio.run(
                send_message(
                    integration_name=args.integration,
                    channel=args.channel,
                    text=args.text,
                    subject=args.subject,
                    user_id=args.user_id,
                )
            )
            _print_json(res)
        elif args.cmd == "broadcast":
            res = asyncio.run(broadcast(args.integration, args.channels, text=args.text, subject=args.subject))
            _print_json(res)
        elif args.cmd == "send-email":
            to_arg = args.to
            # try to parse comma-separated list
            if "," in to_arg:
                to_val = [t.strip() for t in to_arg.split(",") if t.strip()]
            else:
                to_val = to_arg
            res = asyncio.run(send_email(args.integration, to_val, subject=args.subject, body_text=args.body, html=args.html))
            _print_json(res)
        elif args.cmd == "list":
            res = list_integrations()
            _print_json(res)
    except NotificationServiceError as e:
        print("notification service error:", str(e))
    except Exception as exc:
        logger.exception("notification_tools error")
        print("error:", str(exc))


if __name__ == "__main__":
    main()
