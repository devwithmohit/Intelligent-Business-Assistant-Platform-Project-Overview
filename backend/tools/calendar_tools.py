import argparse
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ..integrations.calendar.calendar_service import (
    get_calendar_service,
    CalendarServiceError,
)

logger = logging.getLogger(__name__)


def _parse_dt(value: Union[str, datetime]) -> Union[str, datetime]:
    """
    Accept either ISO8601 string or datetime and return appropriate object.
    Calendar clients in this project accept either dict with dateTime or datetime-like;
    here we preserve string if provided, otherwise return datetime.
    """
    if isinstance(value, datetime):
        return value
    if not value:
        raise ValueError("datetime value required")
    try:
        # try strict isoparse
        return datetime.fromisoformat(value)
    except Exception:
        # fallback: return raw string (clients may accept)
        return value


async def list_events(
    integration_name: str,
    start: Optional[Union[str, datetime]] = None,
    end: Optional[Union[str, datetime]] = None,
    max_results: int = 50,
    q: Optional[str] = None,
) -> List[Dict[str, Any]]:
    svc = get_calendar_service()
    try:
        start_obj = _parse_dt(start) if start else None
        end_obj = _parse_dt(end) if end else None
        return await svc.list_events(integration_name, start=start_obj, end=end_obj, max_results=max_results, q=q)
    except CalendarServiceError as e:
        logger.exception("list_events failed for %s", integration_name)
        raise


async def get_event(integration_name: str, event_id: str) -> Optional[Dict[str, Any]]:
    svc = get_calendar_service()
    try:
        return await svc.get_event(integration_name, event_id)
    except CalendarServiceError as e:
        logger.exception("get_event failed for %s id=%s", integration_name, event_id)
        raise


async def create_event(
    integration_name: str,
    subject: str,
    start: Union[str, datetime],
    end: Union[str, datetime],
    attendees: Optional[List[str]] = None,
    location: Optional[str] = None,
    body: Optional[str] = None,
) -> Dict[str, Any]:
    svc = get_calendar_service()
    try:
        start_obj = _parse_dt(start)
        end_obj = _parse_dt(end)
        # build normalized event body (calendar_interface.create_event_normalized expects specific shapes)
        event_body = {
            "summary": subject,
            "subject": subject,
            "start": {"dateTime": start_obj.isoformat() if isinstance(start_obj, datetime) else str(start_obj)},
            "end": {"dateTime": end_obj.isoformat() if isinstance(end_obj, datetime) else str(end_obj)},
        }
        if attendees:
            # normalized client helper will adapt shape
            event_body["attendees"] = [{"email": a} for a in attendees]
            event_body["attendees_emails"] = attendees
        if location:
            event_body["location"] = location
        if body:
            event_body["body"] = body
        return await svc.create_event(integration_name, event_body)
    except CalendarServiceError as e:
        logger.exception("create_event failed for %s", integration_name)
        raise


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, default=str, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="calendar_tools", description="Calendar integration helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List events")
    p_list.add_argument("integration")
    p_list.add_argument("--start", default=None, help="ISO datetime start")
    p_list.add_argument("--end", default=None, help="ISO datetime end")
    p_list.add_argument("--max", type=int, default=50)
    p_list.add_argument("--q", default=None)

    p_get = sub.add_parser("get", help="Get event by id")
    p_get.add_argument("integration")
    p_get.add_argument("event_id")

    p_create = sub.add_parser("create", help="Create/schedule an event")
    p_create.add_argument("integration")
    p_create.add_argument("subject")
    p_create.add_argument("start", help="ISO datetime start")
    p_create.add_argument("end", help="ISO datetime end")
    p_create.add_argument("--attendees", nargs="*", default=[])
    p_create.add_argument("--location", default=None)
    p_create.add_argument("--body", default=None)

    args = parser.parse_args()

    try:
        if args.cmd == "list":
            try:
                res = asyncio.run(list_events(args.integration, start=args.start, end=args.end, max_results=args.max, q=args.q))
                _print_json(res)
            except Exception as e:
                print("list failed:", str(e))
        elif args.cmd == "get":
            try:
                res = asyncio.run(get_event(args.integration, args.event_id))
                _print_json(res)
            except Exception as e:
                print("get failed:", str(e))
        elif args.cmd == "create":
            try:
                res = asyncio.run(create_event(args.integration, args.subject, args.start, args.end, attendees=args.attendees or None, location=args.location, body=args.body))
                _print_json(res)
            except Exception as e:
                print("create failed:", str(e))
    except Exception as exc:
        logger.exception("calendar_tools error")
        print("error:", str(exc))


if __name__ == "__main__":
    main()
